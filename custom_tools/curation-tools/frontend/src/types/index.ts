export const GRADES = ['Good', 'Normal', 'Bad'] as const;
export type Grade = (typeof GRADES)[number];

export const GRADE_COLORS: Record<string, string> = {
  Good: '#4caf50',
  Normal: '#ffc107',
  Bad: '#f44336',
};

export interface DatasetInfo {
  path: string;
  name: string;
  fps: number;
  total_episodes: number;
  total_tasks: number;
  robot_type: string | null;
  features: Record<string, unknown>;
}

export interface Episode {
  episode_index: number;
  length: number;
  task_index: number;
  task_instruction: string;
  chunk_index: number;
  file_index: number;
  dataset_from_index: number;
  dataset_to_index: number;
  grade: string | null;
  tags: string[];
}

export interface Task {
  task_index: number;
  task_instruction: string;
}

export interface EpisodeUpdate {
  grade: string | null;
  tags: string[];
}

export interface TaskUpdate {
  task_instruction: string;
}
