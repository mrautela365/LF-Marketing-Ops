package model

// AsanaTask is the subset of an Asana task's fields used by the
// plan-from-asana flow, mirroring get_task's opt_fields.
type AsanaTask struct {
	GID          string
	Name         string
	Notes        string
	DueOn        string
	ProjectNames []string
	PermalinkURL string
}

// AsanaSubtask mirrors get_subtasks' opt_fields.
type AsanaSubtask struct {
	GID       string
	Name      string
	Notes     string
	Completed bool
}

// AsanaStory is a comment-type story on a task (system events are filtered
// out by GetStories, matching Python's type == "comment" filter).
type AsanaStory struct {
	Text          string
	Type          string
	CreatedAt     string
	CreatedByName string
}

// EmailBrief is the parsed brief extracted from an Asana task + its
// subtasks + their comment stories, ported from extract_brief.
type EmailBrief struct {
	TaskName             string
	EmailName            string
	BrandName            string
	ProjectName          string
	ContentDocURL        string
	AudienceInstructions string
	EventURL             string
	DueOn                string
	SubtaskNames         []string
}
