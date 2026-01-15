"""Activity matching engine with multi-signal scoring.

Provides intelligent activity-to-project/theme matching using:
1. Path-based matching (highest confidence)
2. Semantic keyword matching with scoring
3. Recent activity context
4. Source-specific hints (Slack channels, git branches)
"""

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource, Roadmap, Project, Theme


@dataclass
class MatchResult:
    """Result of matching an activity."""
    project: Optional[str] = None
    theme_id: Optional[str] = None
    confidence: float = 0.0
    signals: List[str] = None

    def __post_init__(self):
        if self.signals is None:
            self.signals = []


class ActivityMatcher:
    """Score activities against projects/themes using multiple signals."""

    # Signal weights
    PATH_WEIGHT = 0.4       # Path-based matching
    KEYWORD_WEIGHT = 0.25   # Keyword matching
    CONTEXT_WEIGHT = 0.15   # Recent activity context
    SOURCE_WEIGHT = 0.2     # Source-specific hints

    def __init__(self, roadmap: Roadmap, projects_config: Dict[str, Any]):
        self.roadmap = roadmap
        self.projects_config = projects_config
        self._build_lookup_tables()

    def _build_lookup_tables(self):
        """Build efficient lookup structures for matching."""
        self.path_to_project: Dict[str, str] = {}
        self.alias_to_project: Dict[str, str] = {}
        self.channel_to_project: Dict[str, str] = {}
        self.keyword_to_themes: Dict[str, List[Tuple[str, str]]] = defaultdict(list)

        # Build from projects config
        for project in self.projects_config.get("projects", []):
            project_name = project.get("name", "")
            project_id = project.get("id", "")

            # Path mapping
            folder_path = project.get("folder_path", "")
            if folder_path:
                self.path_to_project[folder_path.lower()] = project_name

            # Alias mapping
            for alias in project.get("aliases", []):
                self.alias_to_project[alias.lower()] = project_name

            # Channel mapping
            for channel in project.get("slack_channels", []):
                self.channel_to_project[channel.lower().strip('#')] = project_name

        # Build from roadmap themes
        for project in self.roadmap.projects:
            for theme in project.themes:
                # Extract significant keywords from theme name
                words = theme.name.lower().split()
                for word in words:
                    # Skip common/short words
                    if len(word) > 4 and word not in ['with', 'from', 'this', 'that', 'have']:
                        self.keyword_to_themes[word].append((project.name, theme.id))

    def match_activity(self, activity: Activity) -> MatchResult:
        """
        Match an activity to a project/theme using multiple signals.

        Returns a MatchResult with the best match and confidence score.
        """
        scores = defaultdict(lambda: {"score": 0.0, "signals": [], "theme_id": None})

        # Signal 1: Path-based matching (highest confidence)
        path_match = self._match_by_path(activity)
        if path_match:
            project, confidence = path_match
            scores[project]["score"] += confidence * self.PATH_WEIGHT
            scores[project]["signals"].append(f"path match ({int(confidence * 100)}%)")

        # Signal 2: Keyword matching
        keyword_matches = self._match_by_keywords(activity)
        for project, theme_id, confidence in keyword_matches:
            scores[project]["score"] += confidence * self.KEYWORD_WEIGHT
            scores[project]["signals"].append(f"keyword match")
            if theme_id:
                scores[project]["theme_id"] = theme_id

        # Signal 3: Source-specific hints
        source_match = self._match_by_source(activity)
        if source_match:
            project, confidence = source_match
            scores[project]["score"] += confidence * self.SOURCE_WEIGHT
            scores[project]["signals"].append(f"source hint ({activity.source.value})")

        # Signal 4: Explicit project in raw_data (from collectors)
        if activity.raw_data.get("project"):
            project = activity.raw_data["project"]
            if project != "Unknown" and project != "Slack":
                scores[project]["score"] += 0.8 * self.CONTEXT_WEIGHT
                scores[project]["signals"].append("explicit project")

        # Find best match
        if not scores:
            return MatchResult()

        best_project = max(scores.keys(), key=lambda p: scores[p]["score"])
        best_data = scores[best_project]

        return MatchResult(
            project=best_project,
            theme_id=best_data.get("theme_id"),
            confidence=min(best_data["score"], 1.0),
            signals=best_data["signals"]
        )

    def _match_by_path(self, activity: Activity) -> Optional[Tuple[str, float]]:
        """Match activity by file path."""
        # Check various path fields
        paths_to_check = []

        # From raw_data
        if activity.raw_data.get("folder"):
            paths_to_check.append(activity.raw_data["folder"])
        if activity.raw_data.get("path"):
            paths_to_check.append(activity.raw_data["path"])
        if activity.raw_data.get("cwd"):
            paths_to_check.append(activity.raw_data["cwd"])

        # From files edited/changed
        for f in activity.raw_data.get("files_edited", []):
            paths_to_check.append(f)
        for f in activity.raw_data.get("files_changed", []):
            paths_to_check.append(f)

        # Try to match against known project paths
        for path in paths_to_check:
            path_lower = path.lower() if path else ""
            for project_path, project_name in self.path_to_project.items():
                if project_path in path_lower:
                    # More specific path = higher confidence
                    specificity = len(project_path) / max(len(path_lower), 1)
                    return (project_name, min(0.6 + specificity * 0.4, 1.0))

        return None

    def _match_by_keywords(self, activity: Activity) -> List[Tuple[str, Optional[str], float]]:
        """Match activity by keywords in description."""
        matches = []
        text = activity.description.lower()

        # Also check task descriptions from Claude sessions
        for task in activity.raw_data.get("task_descriptions", []):
            text += " " + task.lower()

        # Match against theme keywords
        matched_keywords = set()
        for keyword, theme_list in self.keyword_to_themes.items():
            if keyword in text and keyword not in matched_keywords:
                matched_keywords.add(keyword)
                for project_name, theme_id in theme_list:
                    matches.append((project_name, theme_id, 0.7))

        # Match against project aliases
        for alias, project_name in self.alias_to_project.items():
            if alias in text:
                matches.append((project_name, None, 0.6))

        return matches

    def _match_by_source(self, activity: Activity) -> Optional[Tuple[str, float]]:
        """Match activity using source-specific hints."""
        if activity.source == ActivitySource.SLACK:
            # Check Slack channels
            channels = activity.raw_data.get("channels", [])
            for channel in channels:
                channel_clean = channel.lower().strip('#')
                if channel_clean in self.channel_to_project:
                    return (self.channel_to_project[channel_clean], 0.9)

        elif activity.source == ActivitySource.GIT:
            # Check git branch for project hints
            branch = activity.raw_data.get("branch", "")
            if branch:
                for alias, project_name in self.alias_to_project.items():
                    if alias in branch.lower():
                        return (project_name, 0.7)

        return None

    def categorize_batch(self, activities: List[Activity]) -> Dict[str, Any]:
        """
        Categorize a batch of activities with confidence scoring.

        Returns:
            {
                "by_project": {project_name: [activities]},
                "by_theme": {theme_id: [activities]},
                "high_confidence": [activities],
                "low_confidence": [activities],
                "uncategorized": [activities],
                "summary": {...}
            }
        """
        result = {
            "by_project": defaultdict(list),
            "by_theme": defaultdict(list),
            "high_confidence": [],
            "low_confidence": [],
            "uncategorized": [],
            "summary": {
                "total_activities": len(activities),
                "projects_touched": set(),
                "sources": defaultdict(int),
                "avg_confidence": 0.0,
            }
        }

        total_confidence = 0.0
        matched_count = 0

        for activity in activities:
            result["summary"]["sources"][activity.source.value] += 1

            match = self.match_activity(activity)

            # Store match info in raw_data for later use
            activity.raw_data["match_confidence"] = match.confidence
            activity.raw_data["match_signals"] = match.signals

            if match.project and match.confidence >= 0.5:
                result["by_project"][match.project].append(activity)
                result["summary"]["projects_touched"].add(match.project)

                if match.theme_id:
                    result["by_theme"][match.theme_id].append(activity)

                if match.confidence >= 0.7:
                    result["high_confidence"].append(activity)
                else:
                    result["low_confidence"].append(activity)

                total_confidence += match.confidence
                matched_count += 1
            else:
                result["uncategorized"].append(activity)

        # Calculate average confidence
        if matched_count > 0:
            result["summary"]["avg_confidence"] = round(total_confidence / matched_count, 2)

        # Convert sets to lists for JSON serialization
        result["summary"]["projects_touched"] = list(result["summary"]["projects_touched"])
        result["summary"]["sources"] = dict(result["summary"]["sources"])

        return result
