package dispatch

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

const asanaBaseURL = "https://app.asana.com/api/1.0"

// AsanaClient ports integrations/asana.py's REST helpers for the
// /api/plan-from-asana route.
type AsanaClient struct {
	httpClient *http.Client
	token      string

	// baseURLOverride replaces asanaBaseURL when set — test-only seam.
	baseURLOverride string
}

var _ domain.AsanaClient = (*AsanaClient)(nil)

// NewAsanaClient builds an Asana adapter. token is ASANA_ACCESS_TOKEN.
func NewAsanaClient(token string) *AsanaClient {
	return &AsanaClient{
		httpClient: &http.Client{Timeout: 15 * time.Second},
		token:      token,
	}
}

func (c *AsanaClient) baseURL() string {
	if c.baseURLOverride != "" {
		return c.baseURLOverride
	}
	return asanaBaseURL
}

func (c *AsanaClient) get(path string, query url.Values, out any) error {
	u := c.baseURL() + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}
	req, err := http.NewRequest(http.MethodGet, u, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("asana: %s %s: %d: %s", http.MethodGet, path, resp.StatusCode, string(body))
	}
	return json.Unmarshal(body, out)
}

// taskGIDRe matches the new-format Asana task URL: .../task/{gid}.
var taskGIDRe = regexp.MustCompile(`/task/(\d+)`)

// ParseTaskGID ports parse_task_gid.
func (c *AsanaClient) ParseTaskGID(taskURL string) (string, error) {
	u := strings.TrimRight(strings.Split(strings.Split(strings.TrimSpace(taskURL), "?")[0], "#")[0], "/")

	if m := taskGIDRe.FindStringSubmatch(u); m != nil {
		return m[1], nil
	}

	if strings.HasSuffix(u, "/f") {
		u = u[:len(u)-2]
	}
	parts := strings.Split(u, "/")
	gid := parts[len(parts)-1]
	if isDigits(gid) {
		return gid, nil
	}

	return "", fmt.Errorf(
		"could not extract a numeric task ID from URL: %s\n"+
			"Expected format: https://app.asana.com/0/<project>/<task_id> "+
			"or https://app.asana.com/1/<workspace>/project/<project>/task/<task_id>",
		u,
	)
}

func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

type asanaTaskResponse struct {
	Data struct {
		GID      string `json:"gid"`
		Name     string `json:"name"`
		Notes    string `json:"notes"`
		DueOn    string `json:"due_on"`
		Projects []struct {
			Name string `json:"name"`
		} `json:"projects"`
		PermalinkURL string `json:"permalink_url"`
	} `json:"data"`
}

// GetTask ports get_task.
func (c *AsanaClient) GetTask(gid string) (model.AsanaTask, error) {
	var resp asanaTaskResponse
	err := c.get(fmt.Sprintf("/tasks/%s", gid), url.Values{
		"opt_fields": {"name,notes,due_on,projects.name,custom_fields,permalink_url"},
	}, &resp)
	if err != nil {
		return model.AsanaTask{}, err
	}
	names := make([]string, 0, len(resp.Data.Projects))
	for _, p := range resp.Data.Projects {
		names = append(names, p.Name)
	}
	return model.AsanaTask{
		GID:          resp.Data.GID,
		Name:         resp.Data.Name,
		Notes:        resp.Data.Notes,
		DueOn:        resp.Data.DueOn,
		ProjectNames: names,
		PermalinkURL: resp.Data.PermalinkURL,
	}, nil
}

type asanaSubtasksResponse struct {
	Data []struct {
		GID       string `json:"gid"`
		Name      string `json:"name"`
		Notes     string `json:"notes"`
		Completed bool   `json:"completed"`
	} `json:"data"`
}

// GetSubtasks ports get_subtasks.
func (c *AsanaClient) GetSubtasks(gid string) ([]model.AsanaSubtask, error) {
	var resp asanaSubtasksResponse
	err := c.get(fmt.Sprintf("/tasks/%s/subtasks", gid), url.Values{
		"opt_fields": {"name,notes,completed,gid"},
	}, &resp)
	if err != nil {
		return nil, err
	}
	out := make([]model.AsanaSubtask, 0, len(resp.Data))
	for _, d := range resp.Data {
		out = append(out, model.AsanaSubtask{GID: d.GID, Name: d.Name, Notes: d.Notes, Completed: d.Completed})
	}
	return out, nil
}

type asanaStoriesResponse struct {
	Data []struct {
		Text      string `json:"text"`
		Type      string `json:"type"`
		CreatedAt string `json:"created_at"`
		CreatedBy struct {
			Name string `json:"name"`
		} `json:"created_by"`
	} `json:"data"`
}

// GetStories ports get_stories — returns only comment-type stories, not
// system events.
func (c *AsanaClient) GetStories(gid string) ([]model.AsanaStory, error) {
	var resp asanaStoriesResponse
	err := c.get(fmt.Sprintf("/tasks/%s/stories", gid), url.Values{
		"opt_fields": {"text,type,created_at,created_by.name"},
	}, &resp)
	if err != nil {
		return nil, err
	}
	out := make([]model.AsanaStory, 0, len(resp.Data))
	for _, d := range resp.Data {
		if d.Type != "comment" {
			continue
		}
		out = append(out, model.AsanaStory{
			Text:          d.Text,
			Type:          d.Type,
			CreatedAt:     d.CreatedAt,
			CreatedByName: d.CreatedBy.Name,
		})
	}
	return out, nil
}

// urlRe ports _urls_in's r"https?://[^\s\)\]>\"',]+".
var urlRe = regexp.MustCompile(`https?://[^\s)\]>"',]+`)

func urlsIn(text string) []string {
	return urlRe.FindAllString(text, -1)
}

func findGoogleDoc(texts []string) string {
	for _, text := range texts {
		for _, u := range urlsIn(text) {
			if strings.Contains(u, "docs.google.com/document") {
				return strings.TrimRight(u, ".,;)")
			}
		}
	}
	return ""
}

// lfDomains ports _LF_DOMAINS.
var lfDomains = []string{
	"linuxfoundation.org", "lfresearch.org", "cncf.io",
	"events.linux", "openssf.org", "pytorch.org", "opensearch.org",
}

func findEventURL(texts []string) string {
	for _, text := range texts {
		for _, u := range urlsIn(text) {
			matched := false
			for _, d := range lfDomains {
				if strings.Contains(u, d) {
					matched = true
					break
				}
			}
			if !matched {
				continue
			}
			skip := false
			for _, s := range []string{"asana.com", "hubspot.com", "docs.google.com"} {
				if strings.Contains(u, s) {
					skip = true
					break
				}
			}
			if skip {
				continue
			}
			return strings.TrimRight(u, ".,;)")
		}
	}
	return ""
}

// brandFromTaskNameRe ports the r"^\d{2}Q\d\s*[-–]\s*(.+?)\s*[-–]" brand
// extraction from a task name like "26Q2 - LF Research - Campaign Name".
var brandFromTaskNameRe = regexp.MustCompile(`^\d{2}Q\d\s*[-–]\s*(.+?)\s*[-–]`)

// ExtractBrief ports extract_brief.
func (c *AsanaClient) ExtractBrief(task model.AsanaTask, subtasks []model.AsanaSubtask, allStories map[string][]model.AsanaStory) model.EmailBrief {
	taskGID := task.GID
	taskName := task.Name
	taskNotes := task.Notes

	allText := []string{taskNotes}
	for _, story := range allStories[taskGID] {
		allText = append(allText, story.Text)
	}
	for _, st := range subtasks {
		allText = append(allText, st.Notes)
		for _, story := range allStories[st.GID] {
			allText = append(allText, story.Text)
		}
	}

	// Google Doc — prioritise "Content" subtask stories.
	contentDocURL := ""
	for _, st := range subtasks {
		if !strings.Contains(strings.ToLower(st.Name), "content") {
			continue
		}
		docTexts := []string{st.Notes}
		for _, s := range allStories[st.GID] {
			docTexts = append(docTexts, s.Text)
		}
		contentDocURL = findGoogleDoc(docTexts)
		if contentDocURL != "" {
			break
		}
	}
	if contentDocURL == "" {
		contentDocURL = findGoogleDoc(allText)
	}

	// Audience instructions — from "List Pull" or "Audience" subtask.
	audienceInstructions := ""
	for _, st := range subtasks {
		nameLower := strings.ToLower(st.Name)
		if !strings.Contains(nameLower, "list pull") && !strings.Contains(nameLower, "list") && !strings.Contains(nameLower, "audience") {
			continue
		}
		parts := []string{st.Notes}
		for _, s := range allStories[st.GID] {
			parts = append(parts, s.Text)
		}
		nonEmpty := make([]string, 0, len(parts))
		for _, p := range parts {
			if strings.TrimSpace(p) != "" {
				nonEmpty = append(nonEmpty, p)
			}
		}
		joined := strings.Join(nonEmpty, "\n")
		if len(joined) > 600 {
			joined = joined[:600]
		}
		audienceInstructions = joined
		break
	}

	eventURL := findEventURL(allText)

	brandName := ""
	if m := brandFromTaskNameRe.FindStringSubmatch(taskName); m != nil {
		brandName = strings.TrimSpace(m[1])
	}

	dueOn := task.DueOn
	projectName := ""
	if len(task.ProjectNames) > 0 {
		projectName = task.ProjectNames[0]
	}

	subtaskNames := make([]string, 0, len(subtasks))
	for _, st := range subtasks {
		subtaskNames = append(subtaskNames, st.Name)
	}

	return model.EmailBrief{
		TaskName:             taskName,
		EmailName:            taskName,
		BrandName:            brandName,
		ProjectName:          projectName,
		ContentDocURL:        contentDocURL,
		AudienceInstructions: audienceInstructions,
		EventURL:             eventURL,
		DueOn:                dueOn,
		SubtaskNames:         subtaskNames,
	}
}
