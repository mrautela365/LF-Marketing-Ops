package domain

import "github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"

// AsanaClient reads Asana tasks/subtasks/comments and extracts an Email
// Brief, porting integrations/asana.py for the /api/plan-from-asana route.
type AsanaClient interface {
	// ParseTaskGID extracts a numeric task GID from an Asana task URL —
	// ports parse_task_gid. Returns an error if no numeric ID is found.
	ParseTaskGID(taskURL string) (string, error)

	// GetTask ports get_task.
	GetTask(gid string) (model.AsanaTask, error)

	// GetSubtasks ports get_subtasks.
	GetSubtasks(gid string) ([]model.AsanaSubtask, error)

	// GetStories ports get_stories — returns only comment-type stories.
	GetStories(gid string) ([]model.AsanaStory, error)

	// ExtractBrief ports extract_brief. allStories maps task GID (task or
	// subtask) to that task's comment stories.
	ExtractBrief(task model.AsanaTask, subtasks []model.AsanaSubtask, allStories map[string][]model.AsanaStory) model.EmailBrief
}
