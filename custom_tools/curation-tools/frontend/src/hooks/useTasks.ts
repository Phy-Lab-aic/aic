import { useState, useCallback } from 'react'
import client from '../api/client'
import type { Task, TaskUpdate } from '../types'

interface UseTasksReturn {
  tasks: Task[]
  loading: boolean
  error: string | null
  fetchTasks: () => Promise<void>
  updateTask: (taskIndex: number, instruction: string) => Promise<void>
}

export function useTasks(): UseTasksReturn {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchTasks = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await client.get<Task[]>('/tasks')
      setTasks(response.data)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch tasks'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  const updateTask = useCallback(async (taskIndex: number, instruction: string) => {
    const update: TaskUpdate = { task_instruction: instruction }
    const response = await client.patch<Task>(`/tasks/${taskIndex}`, update)
    const updated = response.data
    setTasks(prev => prev.map(t => t.task_index === taskIndex ? updated : t))
  }, [])

  return { tasks, loading, error, fetchTasks, updateTask }
}
