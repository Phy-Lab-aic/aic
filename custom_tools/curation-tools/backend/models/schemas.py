from pydantic import BaseModel, field_validator


class DatasetInfo(BaseModel):
    path: str
    name: str
    fps: int
    total_episodes: int
    total_tasks: int
    robot_type: str | None = None
    features: dict = {}


class Episode(BaseModel):
    episode_index: int
    length: int
    task_index: int
    task_instruction: str = ""
    chunk_index: int = 0
    file_index: int = 0
    dataset_from_index: int = 0
    dataset_to_index: int = 0
    grade: str | None = None
    tags: list[str] = []


class Task(BaseModel):
    task_index: int
    task_instruction: str


class EpisodeUpdate(BaseModel):
    grade: str | None = None
    tags: list[str] | None = None

    @field_validator("grade")
    @classmethod
    def validate_grade(cls, v: str | None) -> str | None:
        if v is not None and v not in ("Good", "Normal", "Bad"):
            raise ValueError("Grade must be one of: Good, Normal, Bad")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            v = [t.strip() for t in v if t.strip()]
        return v


class TaskUpdate(BaseModel):
    task_instruction: str


class DatasetLoadRequest(BaseModel):
    path: str


class DatasetExportRequest(BaseModel):
    output_path: str
    exclude_grades: list[str] = ["Bad"]
