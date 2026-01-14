"""Data models for the task tracking system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List
import json


class ActivitySource(Enum):
    FILESYSTEM = "filesystem"
    GIT = "git"
    CLAUDE = "claude"
    SLACK = "slack"
    MANUAL = "manual"


class TaskStatus(Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class ThemeStatus(Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETE = "complete"


class Privacy(Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass
class Activity:
    """Raw detected activity from any source."""
    source: ActivitySource
    timestamp: datetime
    description: str
    confidence: float = 1.0
    raw_data: dict = field(default_factory=dict)
    project_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "confidence": self.confidence,
            "raw_data": self.raw_data,
            "project_path": self.project_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Activity":
        return cls(
            source=ActivitySource(data["source"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            description=data["description"],
            confidence=data.get("confidence", 1.0),
            raw_data=data.get("raw_data", {}),
            project_path=data.get("project_path"),
        )


@dataclass
class Task:
    """A specific task within a theme."""
    id: str
    description: str
    status: TaskStatus = TaskStatus.TODO
    last_touched: Optional[datetime] = None
    artifacts: List[str] = field(default_factory=list)
    activities: List["Activity"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "last_touched": self.last_touched.isoformat() if self.last_touched else None,
            "artifacts": self.artifacts,
            "activities": [a.to_dict() for a in self.activities],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            id=data["id"],
            description=data["description"],
            status=TaskStatus(data["status"]),
            last_touched=datetime.fromisoformat(data["last_touched"]) if data.get("last_touched") else None,
            artifacts=data.get("artifacts", []),
            activities=[Activity.from_dict(a) for a in data.get("activities", [])],
        )


@dataclass
class Theme:
    """A work theme/initiative (e.g., 'Auth System Redesign')."""
    id: str
    name: str
    status: ThemeStatus = ThemeStatus.PLANNED
    notes: str = ""
    tasks: List["Task"] = field(default_factory=list)
    last_touched: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "notes": self.notes,
            "tasks": [t.to_dict() for t in self.tasks],
            "last_touched": self.last_touched.isoformat() if self.last_touched else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Theme":
        return cls(
            id=data["id"],
            name=data["name"],
            status=ThemeStatus(data["status"]),
            notes=data.get("notes", ""),
            tasks=[Task.from_dict(t) for t in data.get("tasks", [])],
            last_touched=datetime.fromisoformat(data["last_touched"]) if data.get("last_touched") else None,
        )


@dataclass
class Project:
    """A project mapped to a folder."""
    id: str
    name: str
    team: str
    folder_path: str
    privacy: Privacy = Privacy.PUBLIC
    themes: List["Theme"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "team": self.team,
            "folder_path": self.folder_path,
            "privacy": self.privacy.value,
            "themes": [t.to_dict() for t in self.themes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        return cls(
            id=data["id"],
            name=data["name"],
            team=data["team"],
            folder_path=data["folder_path"],
            privacy=Privacy(data.get("privacy", "public")),
            themes=[Theme.from_dict(t) for t in data.get("themes", [])],
        )


@dataclass
class ProposedChange:
    """A proposed change to the roadmap awaiting approval."""
    id: str
    change_type: str  # "new_theme", "status_change", "new_task", etc.
    description: str
    details: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    approved: Optional[bool] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "change_type": self.change_type,
            "description": self.description,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
            "approved": self.approved,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProposedChange":
        return cls(
            id=data["id"],
            change_type=data["change_type"],
            description=data["description"],
            details=data.get("details", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            approved=data.get("approved"),
        )


@dataclass
class Roadmap:
    """The complete roadmap state."""
    version: str = "1.0"
    last_updated: Optional[datetime] = None
    projects: List["Project"] = field(default_factory=list)
    pending_changes: List["ProposedChange"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "projects": [p.to_dict() for p in self.projects],
            "pending_changes": [c.to_dict() for c in self.pending_changes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Roadmap":
        return cls(
            version=data.get("version", "1.0"),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else None,
            projects=[Project.from_dict(p) for p in data.get("projects", [])],
            pending_changes=[ProposedChange.from_dict(c) for c in data.get("pending_changes", [])],
        )

    def save(self, path: str) -> None:
        """Save roadmap to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Roadmap":
        """Load roadmap from JSON file."""
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))
