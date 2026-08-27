package wizardagent

import "github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"

// forbiddenTools ports _FORBIDDEN_TOOLS verbatim.
var forbiddenTools = map[string]bool{
	"delete_email":   true,
	"delete_list":    true,
	"delete_contact": true,
	"archive_email":  true,
}

// writeTools ports _WRITE_TOOLS verbatim.
var writeTools = map[string]bool{
	"update_email_settings": true,
	"update_email_content":  true,
}

// checkToolSafety ports the safety-gate portion of _execute_tool (the two
// "if name in _FORBIDDEN_TOOLS" / "if name in _WRITE_TOOLS" blocks, before
// the tool dispatch switch). Python keeps this state in process-global
// _session_email_id / _session_email_ids_allowed; here it is scoped to the
// given session via model.SessionState.EmailIDsAllowed, plus the optional
// sessionEmailID carried alongside it (mirroring _execute_tool's
// session_email_id parameter, which Python ORs in alongside the globals).
//
// Returns (blocked, errorJSON). When blocked is true, execute_tool.go must
// return errorJSON immediately without dispatching the tool.
func checkToolSafety(name string, inputs map[string]any, session *model.SessionState, sessionEmailID string) (bool, string) {
	if forbiddenTools[name] {
		return true, jsonError("Tool '" + name + "' is not permitted. This service never deletes or archives.")
	}

	if writeTools[name] {
		allowed := map[string]bool{}
		if session != nil {
			for id, ok := range session.EmailIDsAllowed {
				if ok {
					allowed[id] = true
				}
			}
		}
		if sessionEmailID != "" {
			allowed[sessionEmailID] = true
		}

		if len(allowed) == 0 {
			return true, jsonError("No email has been cloned in this session yet. Clone first.")
		}

		targetID, _ := inputs["email_id"].(string)
		if !allowed[targetID] {
			return true, jsonError("Write blocked: email " + targetID + " was not created by this session. Only emails " + formatAllowedSet(allowed) + " (cloned in this session) may be modified.")
		}
	}

	return false, ""
}

// allowSessionEmail ports the clone_email branch's
// `_session_email_id = new_email_id; _session_email_ids_allowed.add(new_email_id)`
// side effect, scoped to session instead of process globals.
func allowSessionEmail(session *model.SessionState, emailID string) {
	if session == nil || emailID == "" {
		return
	}
	if session.EmailIDsAllowed == nil {
		session.EmailIDsAllowed = map[string]bool{}
	}
	session.EmailIDsAllowed[emailID] = true
}
