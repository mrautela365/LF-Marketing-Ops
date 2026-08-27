package dispatch

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"google.golang.org/api/docs/v1"
	"google.golang.org/api/option"
)

// docIDRe ports _extract_doc_id's r"/document/d/([a-zA-Z0-9_-]+)".
var docIDRe = regexp.MustCompile(`/document/d/([a-zA-Z0-9_-]+)`)

func extractDocID(rawURL string) (string, error) {
	m := docIDRe.FindStringSubmatch(rawURL)
	if m == nil {
		return "", fmt.Errorf("could not extract document ID from URL: %s", rawURL)
	}
	return m[1], nil
}

// fetchGoogleDoc ports _fetch_google_doc.
func (w *WebScraper) fetchGoogleDoc(rawURL string) (string, error) {
	if w.googleServiceAccountFile == "" {
		return "", fmt.Errorf(
			"Google Service Account file is not configured (GOOGLE_SERVICE_ACCOUNT_FILE). " +
				"Please paste the email content directly instead of providing a Google Doc URL.",
		)
	}
	docID, err := extractDocID(rawURL)
	if err != nil {
		return "", err
	}

	ctx := context.Background()
	svc, err := docs.NewService(ctx,
		option.WithCredentialsFile(w.googleServiceAccountFile),
		option.WithScopes(docs.DocumentsReadonlyScope),
	)
	if err != nil {
		return "", err
	}
	doc, err := svc.Documents.Get(docID).Do()
	if err != nil {
		return "", err
	}
	return docToHTML(doc), nil
}

// docToHTML ports _doc_to_html.
func docToHTML(doc *docs.Document) string {
	inlineObjects := doc.InlineObjects

	var parts []string
	if doc.Body != nil {
		for _, elem := range doc.Body.Content {
			para := elem.Paragraph
			if para == nil {
				continue
			}
			style := "NORMAL_TEXT"
			if para.ParagraphStyle != nil && para.ParagraphStyle.NamedStyleType != "" {
				style = para.ParagraphStyle.NamedStyleType
			}

			var runs []string
			for _, pe := range para.Elements {
				if tr := pe.TextRun; tr != nil {
					text := strings.TrimRight(tr.Content, "\n")
					if text == "" {
						continue
					}
					if tr.TextStyle != nil {
						if tr.TextStyle.Bold {
							text = "<strong>" + text + "</strong>"
						}
						if tr.TextStyle.Italic {
							text = "<em>" + text + "</em>"
						}
						if tr.TextStyle.Link != nil && tr.TextStyle.Link.Url != "" {
							text = fmt.Sprintf(`<a href="%s">%s</a>`, tr.TextStyle.Link.Url, text)
						}
					}
					runs = append(runs, text)
					continue
				}

				if inline := pe.InlineObjectElement; inline != nil {
					obj := inlineObjects[inline.InlineObjectId]
					var imgProps *docs.EmbeddedObject
					if obj.InlineObjectProperties != nil {
						imgProps = obj.InlineObjectProperties.EmbeddedObject
					}
					if imgProps != nil && imgProps.ImageProperties != nil {
						src := imgProps.ImageProperties.SourceUri
						if src == "" {
							src = imgProps.ImageProperties.ContentUri
						}
						alt := imgProps.Title
						if alt == "" {
							alt = imgProps.Description
						}
						if src != "" {
							runs = append(runs, fmt.Sprintf(
								`<img src="%s" alt="%s" style="max-width:100%%;height:auto;display:block;" />`,
								src, alt,
							))
						}
					}
				}
			}

			line := strings.TrimSpace(strings.Join(runs, ""))
			if line == "" {
				continue
			}
			if strings.HasPrefix(style, "HEADING_") {
				level := style[len(style)-1:]
				parts = append(parts, fmt.Sprintf("<h%s>%s</h%s>", level, line, level))
			} else {
				parts = append(parts, "<p>"+line+"</p>")
			}
		}
	}
	return strings.Join(parts, "\n")
}
