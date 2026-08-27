package wizardagent

import (
	"context"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// FetchedAsanaTask is the exported shape of fetchAsanaTaskViaMCP's success
// result, for POST /api/plan-from-asana's MCP-fallback path (used only when
// ASANA_ACCESS_TOKEN isn't configured).
type FetchedAsanaTask struct {
	EmailName    string
	SubtaskNames []string
	Raw          map[string]any
}

// FetchAsanaTaskViaMCP is an exported wrapper around fetchAsanaTaskViaMCP —
// see that function's doc comment for the CLI-only-reachability contract.
// ok mirrors the unexported function's own "capability produced a usable
// result" signal (false when a.CLI is nil, the CLI call didn't report
// success, or the response wasn't parseable JSON).
func (a *Agent) FetchAsanaTaskViaMCP(ctx context.Context, taskURL string) (*FetchedAsanaTask, bool, error) {
	res, ok, err := a.fetchAsanaTaskViaMCP(ctx, taskURL)
	if res == nil {
		return nil, ok, err
	}
	return &FetchedAsanaTask{EmailName: res.EmailName, SubtaskNames: res.SubtaskNames, Raw: res.Raw}, ok, err
}

// SectionsToHTML is a thin exported wrapper around sectionsToHTML, letting
// the HTTP layer (POST /api/update-sections) rebuild an email's body HTML
// deterministically without duplicating the section-rendering rules here.
// No turn logic is changed by this wrapper — it forwards verbatim.
func (a *Agent) SectionsToHTML(sections []model.EmailSection, btnColor string, sponsors []model.Sponsor) string {
	return sectionsToHTML(sections, btnColor, sponsors)
}

// BuildEmailPreview is a thin exported wrapper around buildEmailPreview, for
// the same reason as SectionsToHTML above.
func (a *Agent) BuildEmailPreview(bannerURL, bodyHTML, eventURL, eventName string) string {
	return buildEmailPreview(bannerURL, bodyHTML, eventURL, eventName)
}

// SetEmailSendList is a thin exported wrapper around setEmailSendList, for
// POST /api/set-send-list — the ILS-vs-legacy namespace split logic lives
// only in setEmailSendList (also used by CloneTurn's final step) and must
// not be duplicated at the HTTP layer. Returns SetSendListResult so the
// handler can report list_type/to/success exactly as Python's
// set_email_send_list dict does, instead of hardcoding them.
func (a *Agent) SetEmailSendList(ctx context.Context, emailID string, sendListIDs, suppressionListIDs []string) (SetSendListResult, error) {
	return a.setEmailSendList(ctx, emailID, sendListIDs, suppressionListIDs)
}
