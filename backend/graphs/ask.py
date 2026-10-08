import operator
from typing import Annotated, List

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from backend.ai.provision import provision_langchain_model
from backend.domain.notebook import vector_search
from backend.exceptions import (
    ExternalServiceError,
    IncompleteGenerationError,
    OpenNotebookError,
)
from backend.utils import clean_thinking_content
from backend.utils.error_classifier import classify_error
from backend.utils.text_utils import extract_text_content
from backend.utils.web_search import search_web

# Output budget shared by the three Ask stages (strategy, per-search answers,
# final synthesis). Matches chat and transformations. The previous 2000 cap
# silently truncated answers in token-dense languages and left reasoning
# models with no budget for the visible answer after their thinking (#1221).
ASK_MAX_TOKENS = 8192


class SubGraphState(TypedDict):
    question: str
    term: str
    instructions: str
    results: dict
    answer: str
    ids: list  # Added for provide_answer function
    notebook_ids: list  # Notebook scope forwarded from ThreadState (#574, #87)


class Search(BaseModel):
    term: str
    instructions: str = Field(
        description="Tell the answeting LLM what information you need extracted from this search"
    )


class Strategy(BaseModel):
    reasoning: str
    searches: List[Search] = Field(
        default_factory=list,
        description="You can add up to five searches to this strategy",
    )


class ThreadState(TypedDict):
    question: str
    strategy: Strategy
    answers: Annotated[list, operator.add]
    final_answer: str
    # Optional notebook scope: when non-empty, every search the strategy fans
    # out runs only against sources/notes linked to these notebooks (#574, #87).
    notebook_ids: list
    web_search: bool  # Flag indicating whether live web search is enabled
    web_results: list  # Web search citations and snippets


async def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        parser: PydanticOutputParser[Strategy] = PydanticOutputParser(
            pydantic_object=Strategy
        )
        system_prompt = Prompter(prompt_template="ask/entry", parser=parser).render(  # type: ignore[arg-type]
            data=state  # type: ignore[arg-type]
        )
        model = await provision_langchain_model(
            system_prompt,
            config.get("configurable", {}).get("strategy_model"),
            "tools",
            max_tokens=ASK_MAX_TOKENS,
            structured=dict(type="json"),
        )
        # model = model.bind_tools(tools)
        # First get the raw response from the model
        ai_message = await model.ainvoke(system_prompt)

        # Clean the thinking content from the response
        message_content = extract_text_content(ai_message.content)
        cleaned_content = clean_thinking_content(message_content)

        # Parse the cleaned JSON content
        strategy = parser.parse(cleaned_content)

        # A reasoning model that spends its whole budget thinking returns a
        # syntactically valid strategy with blank search terms. Drop those and
        # fail loudly when nothing usable remains, instead of running empty
        # vector searches and answering "no documents found".
        strategy.searches = [s for s in strategy.searches if s.term.strip()]
        if not strategy.searches:
            raise ExternalServiceError(
                "The strategy model returned no search terms for this question. "
                "This usually means the model spent its output budget on reasoning "
                "or returned an empty response. Pick a different strategy model in "
                "the Ask page's advanced model options, or rephrase the question."
            )

        return {"strategy": strategy}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


async def trigger_queries(state: ThreadState, config: RunnableConfig):
    return [
        Send(
            "provide_answer",
            {
                "question": state["question"],
                "instructions": s.instructions,
                "term": s.term,
                "notebook_ids": state.get("notebook_ids") or [],
                # "type": s.type,
            },
        )
        for s in state["strategy"].searches
    ]


async def provide_answer(state: SubGraphState, config: RunnableConfig) -> dict:
    try:
        payload = state
        # if state["type"] == "text":
        #     results = text_search(state["term"], 10, True, True)
        # else:
        results = await vector_search(
            state["term"],
            10,
            True,
            True,
            notebook_ids=state.get("notebook_ids") or None,
        )
        if len(results) == 0:
            return {"answers": []}
        payload["results"] = results
        ids = [r["id"] for r in results]
        payload["ids"] = ids
        system_prompt = Prompter(prompt_template="ask/query_process").render(
            data=payload  # type: ignore[arg-type]
        )
        model = await provision_langchain_model(
            system_prompt,
            config.get("configurable", {}).get("answer_model"),
            "tools",
            max_tokens=ASK_MAX_TOKENS,
        )
        ai_message = await model.ainvoke(system_prompt)
        ai_content = clean_thinking_content(extract_text_content(ai_message.content))
        if not ai_content.strip():
            # Nothing left after stripping thinking content — an empty partial
            # answer only pollutes the final synthesis.
            return {"answers": []}
        return {"answers": [ai_content]}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


async def perform_web_search_if_enabled(state: ThreadState, config: RunnableConfig) -> dict:
    """If web_search is requested, query the web for real-time sources and extract citations."""
    if not state.get("web_search"):
        return {"web_results": []}

    try:
        searches = state.get("strategy", Strategy(reasoning="", searches=[])).searches
        search_terms = [s.term for s in searches if s.term.strip()]
        if not search_terms:
            search_terms = [state["question"]]

        web_hits = []
        seen_urls = set()
        for term in search_terms[:3]:  # Top 3 terms
            results = await search_web(term, max_results=4)
            for r in results:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    web_hits.append(r)
                if len(web_hits) >= 8:
                    break
            if len(web_hits) >= 8:
                break

        if not web_hits:
            return {"web_results": []}

        # Formulate web summary & citations
        web_context_text = "\n\n".join(
            f"[{idx + 1}] Title: {hit['title']}\nURL: {hit['url']}\nSnippet: {hit['snippet']}"
            for idx, hit in enumerate(web_hits)
        )

        web_prompt = (
            f"You are synthesizing web search results for the user's question:\n"
            f"Question: {state['question']}\n\n"
            f"Web Results Found:\n{web_context_text}\n\n"
            f"Provide a concise, factual summary synthesizing key information from these web sources. "
            f"Crucially, cite every claim using standard markdown links with the actual source URL: "
            f"[Source Title](source_url). Also list the references cleanly."
        )

        model = await provision_langchain_model(
            web_prompt,
            config.get("configurable", {}).get("answer_model"),
            "tools",
            max_tokens=ASK_MAX_TOKENS,
        )
        ai_message = await model.ainvoke(web_prompt)
        ai_content = clean_thinking_content(extract_text_content(ai_message.content))

        formatted_answer = (
            f"### 🌐 Web Research Results\n\n{ai_content}\n\n"
            f"**Web Sources Cited:**\n" +
            "\n".join(f"- [{hit['title']}]({hit['url']})" for hit in web_hits[:6])
        )

        return {"web_results": web_hits, "answers": [formatted_answer]}
    except Exception as e:
        logger.warning(f"Web search node error in ask graph: {e}")
        return {"web_results": []}


async def write_final_answer(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        # If web results were obtained, augment prompt context with web sources
        synthesis_state = dict(state)
        web_sources = state.get("web_results") or []
        if web_sources:
            web_summary_text = "\n\n# LIVE WEB SOURCES RETRIEVED (Perplexity-style Live Research):\n" + "\n".join(
                f"- [{w['title']}]({w['url']}): {w['snippet']}"
                for w in web_sources
            )
            # Append web instructions to final answer prompt
            synthesis_state["question"] = (
                f"{state['question']}\n\n"
                f"NOTE: The user has live web search enabled. In addition to any notebook documents, "
                f"use the web search results below to answer comprehensively if the knowledge base documents "
                f"are incomplete or missing information. Always cite web sources using clickable markdown links: "
                f"[Source Name](URL).\n{web_summary_text}"
            )

        system_prompt = Prompter(prompt_template="ask/final_answer").render(data=synthesis_state)  # type: ignore[arg-type]
        model = await provision_langchain_model(
            system_prompt,
            config.get("configurable", {}).get("final_answer_model"),
            "tools",
            max_tokens=ASK_MAX_TOKENS,
        )
        ai_message = await model.ainvoke(system_prompt)
        final_content = clean_thinking_content(extract_text_content(ai_message.content))
        if not final_content.strip():
            raise IncompleteGenerationError(
                "The final answer model returned an empty response. Try again, or "
                "pick a different final answer model in the Ask page's advanced "
                "model options."
            )

        # Append clean web reference footnotes if web results were used and not already linked
        if web_sources and "[http" not in final_content and "](" not in final_content:
            final_content += "\n\n---\n### 🌐 Web Sources Cited\n" + "\n".join(
                f"- [{w['title']}]({w['url']})" for w in web_sources[:5]
            )

        return {"final_answer": final_content}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


agent_state = StateGraph(ThreadState)
agent_state.add_node("agent", call_model_with_messages)
agent_state.add_node("web_search", perform_web_search_if_enabled)
agent_state.add_node("provide_answer", provide_answer)
agent_state.add_node("write_final_answer", write_final_answer)
agent_state.add_edge(START, "agent")
agent_state.add_edge("agent", "web_search")
agent_state.add_conditional_edges("agent", trigger_queries, ["provide_answer"])
agent_state.add_edge("provide_answer", "write_final_answer")
agent_state.add_edge("web_search", "write_final_answer")
agent_state.add_edge("write_final_answer", END)

graph = agent_state.compile()
