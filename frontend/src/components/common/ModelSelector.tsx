import { useId, useMemo } from 'react'
import { Label } from '@/components/ui/label'
import { ModelCombobox } from '@/components/common/ModelCombobox'
import { useModels } from '@/lib/hooks/use-models'

interface ModelSelectorProps {
  id?: string
  name?: string
  label?: string
  modelType: 'language' | 'embedding' | 'speech_to_text' | 'text_to_speech'
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  className?: string
}

export function ModelSelector({
  id,
  name,
  label,
  modelType,
  value,
  onChange,
  placeholder,
  disabled = false,
  className,
}: ModelSelectorProps) {
  const { data: models, isLoading } = useModels()
  const derivedId = useId()
  const selectId = id || derivedId

  const filteredModels = useMemo(() => {
    return models?.filter((m) => m.type === modelType) || []
  }, [models, modelType])

  return (
    <div className="space-y-2">
      {label && <Label htmlFor={selectId}>{label}</Label>}
      <ModelCombobox
        id={selectId}
        name={name}
        models={filteredModels}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={disabled}
        isLoading={isLoading}
        className={className}
      />
    </div>
  )
}
