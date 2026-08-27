package wizardagent

import (
	"encoding/json"
	"regexp"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// messageJSONBlocks scans a single message's flat Content string for every
// balanced-brace JSON object substring it contains, decoding each into a
// map. This stands in for Python's structured content-block iteration
// (messages are lists of {"type": "tool_result", "content": {...}} dicts
// under the SDK backends) — here, since domain.Message/model.AgentMessage
// flatten content to a string, tool-result payloads (when present at all)
// appear as JSON substrings within that string instead. See turns.go's doc
// comment: under the CLI backend, tool-result content isn't persisted into
// message history at all, so these scans are a forward-compatible
// best-effort, not something the CLI backend can currently satisfy.
func messageJSONBlocks(content string) []map[string]any {
	var blocks []map[string]any
	remaining := content
	for {
		block, ok := balancedJSONBlock(remaining)
		if !ok {
			break
		}
		var data map[string]any
		if err := json.Unmarshal([]byte(block), &data); err == nil {
			blocks = append(blocks, data)
		}
		idx := strings.Index(remaining, block)
		if idx < 0 {
			break
		}
		remaining = remaining[idx+len(block):]
	}
	return blocks
}

var useVariantRe = regexp.MustCompile(`(?i)use\s+variant\s+([v\d_a-z]+)`)

// ExtractVariantIDFromMessages ports extract_variant_id_from_messages —
// reversed iteration (most recent message first), preferring a tool_result
// block carrying "selected" + "variant_id", falling back to a
// "use variant <id>" regex match on plain text.
func ExtractVariantIDFromMessages(messages []model.AgentMessage) (string, bool) {
	for i := len(messages) - 1; i >= 0; i-- {
		content := messages[i].Content
		for _, block := range messageJSONBlocks(content) {
			if selected, _ := block["selected"].(bool); selected {
				if variantID, ok := block["variant_id"].(string); ok && variantID != "" {
					return variantID, true
				}
			}
		}
		if m := useVariantRe.FindStringSubmatch(content); m != nil {
			return strings.ToLower(m[1]), true
		}
	}
	return "", false
}

// checkBrandHistoryBlock ports extract_brand_history_from_messages' inner
// _check_block helper: reports a match on "found" + (matched_email_id or
// last_email_id), normalizing matched_email_id -> last_email_id and
// matched_email_name -> last_email_name in place.
func checkBrandHistoryBlock(block map[string]any) (map[string]any, bool) {
	found, _ := block["found"].(bool)
	if !found {
		return nil, false
	}
	if v, ok := block["matched_email_id"]; ok {
		block["last_email_id"] = v
	}
	if v, ok := block["matched_email_name"]; ok {
		block["last_email_name"] = v
	}
	if _, ok := block["last_email_id"]; !ok {
		return nil, false
	}
	return block, true
}

// ExtractBrandHistoryFromMessages ports extract_brand_history_from_messages
// — iterates messages in ORIGINAL order (not reversed, unlike the other two
// extractors) and returns the FIRST matching tool_result block.
func ExtractBrandHistoryFromMessages(messages []model.AgentMessage) (map[string]any, bool) {
	for _, msg := range messages {
		for _, block := range messageJSONBlocks(msg.Content) {
			if result, ok := checkBrandHistoryBlock(block); ok {
				return result, true
			}
		}
	}
	return nil, false
}

// ExtractEmailIDFromMessages ports extract_email_id_from_messages —
// reversed iteration, returns the first tool_result block's "email_id".
func ExtractEmailIDFromMessages(messages []model.AgentMessage) (string, bool) {
	for i := len(messages) - 1; i >= 0; i-- {
		for _, block := range messageJSONBlocks(messages[i].Content) {
			if emailID, ok := block["email_id"].(string); ok && emailID != "" {
				return emailID, true
			}
		}
	}
	return "", false
}
