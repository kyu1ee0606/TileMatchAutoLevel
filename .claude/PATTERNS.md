# Code Patterns

## Backend

### API Route
```python
@router.post("/endpoint")
async def endpoint(request: Schema) -> ResponseSchema:
    return service.process(request)
```

### Pydantic Model
```python
class LevelJSON(BaseModel):
    layer: int
    model_config = ConfigDict(extra="allow")
```

## Frontend

### Zustand Store
```typescript
export const useStore = create<State>((set) => ({
  value: initial,
  setValue: (v) => set({ value: v }),
}));
```

### React Query
```typescript
const { data } = useQuery({
  queryKey: ['key'],
  queryFn: () => api.fetch(),
});
```

### Component
```typescript
export function Component({ prop }: Props) {
  return <div className="tailwind-classes">{prop}</div>;
}
```

## Conventions
- Backend: snake_case
- Frontend: camelCase
- Components: PascalCase
- CSS: TailwindCSS utilities
