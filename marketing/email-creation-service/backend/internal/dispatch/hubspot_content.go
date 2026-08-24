package dispatch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/utmtools"
)

// systemPhrasesContent are substrings that mark a rich_text widget as a
// HubSpot system artifact (view-in-browser, unsubscribe, footer text, etc.)
// that must never be replicated into AI-generated content — ports the
// filter list inside get_email_content_text.
var systemPhrasesContent = []string{
	"view in browser", "view this email in", "view email in browser",
	"unsubscribe", "subscription center",
	"2810 n church", "wilmington, delaware",
	"this email was sent by",
	"thank you to our sponsors", "check out all our sponsors",
	"follow us",
}

var (
	brTagRe    = regexp.MustCompile(`(?i)<br\s*/?>`)
	blockTagRe = regexp.MustCompile(`(?i)</?(p|div|tr)[^>]*>`)
	headTagRe  = regexp.MustCompile(`(?i)</?h[1-6][^>]*>`)
	liTagRe    = regexp.MustCompile(`(?i)<li[^>]*>`)
	anyTagRe   = regexp.MustCompile(`<[^>]+>`)
	spaceRunRe = regexp.MustCompile(`[ \t]+`)
	tripleNlRe = regexp.MustCompile(`\n{3,}`)
)

func widgetBody(topWidgets map[string]any, wid string) map[string]any {
	w, _ := topWidgets[wid].(map[string]any)
	body, _ := w["body"].(map[string]any)
	return body
}

func stringField(m map[string]any, key string) string {
	if m == nil {
		return ""
	}
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func stringifyDestination(v any) string {
	if v == nil {
		return ""
	}
	return fmt.Sprintf("%v", v)
}

func stripHTMLToText(html string) string {
	s := brTagRe.ReplaceAllString(html, "\n")
	s = blockTagRe.ReplaceAllString(s, "\n")
	s = headTagRe.ReplaceAllString(s, "\n")
	s = liTagRe.ReplaceAllString(s, "• ")
	s = anyTagRe.ReplaceAllString(s, "")
	s = spaceRunRe.ReplaceAllString(s, " ")
	s = tripleNlRe.ReplaceAllString(s, "\n\n")
	return strings.TrimSpace(s)
}

func stripHTMLBlocks(htmlParts []string) string {
	var stripped []string
	for _, h := range htmlParts {
		if strings.TrimSpace(h) == "" {
			continue
		}
		stripped = append(stripped, stripHTMLToText(h))
	}
	out := tripleNlRe.ReplaceAllString(strings.Join(stripped, "\n\n"), "\n\n")
	return strings.TrimSpace(out)
}

// GetEmailContentText ports get_email_content_text.
func (c *HubSpotClient) GetEmailContentText(ctx context.Context, emailID string) (*model.EmailContentText, error) {
	var email map[string]any
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails/"+emailID, nil, nil, &email); err != nil {
		return &model.EmailContentText{Success: false, EmailID: emailID, Error: err.Error()}, nil
	}

	content, _ := email["content"].(map[string]any)
	subject := stringField(email, "subject")
	name := stringField(email, "name")

	topWidgets, _ := content["widgets"].(map[string]any)
	if topWidgets == nil {
		topWidgets = map[string]any{}
	}

	previewText := stringField(widgetBody(topWidgets, "preview_text"), "value")

	var htmlParts []string
	var sectionsOut []model.ContentSection

	flexAreas, _ := content["flexAreas"].(map[string]any)
	for _, areaRaw := range flexAreas {
		area, _ := areaRaw.(map[string]any)
		sections, _ := area["sections"].([]any)
		for _, secRaw := range sections {
			section, _ := secRaw.(map[string]any)
			columns, _ := section["columns"].([]any)

			if len(columns) > 1 {
				var images []model.SectionImage
				for _, colRaw := range columns {
					col, _ := colRaw.(map[string]any)
					widgetIDs, _ := col["widgets"].([]any)
					for _, widRaw := range widgetIDs {
						wid, ok := widRaw.(string)
						if !ok {
							continue
						}
						body := widgetBody(topWidgets, wid)
						img, _ := body["img"].(map[string]any)
						src := stringField(img, "src")
						if src == "" {
							continue
						}
						images = append(images, model.SectionImage{Src: src, Alt: stringField(img, "alt")})
					}
				}
				if len(images) > 0 {
					sectionsOut = append(sectionsOut, model.ContentSection{Type: "image_row", Images: images})
				}
				continue
			}

			for _, colRaw := range columns {
				col, _ := colRaw.(map[string]any)
				widgetIDs, _ := col["widgets"].([]any)
				for _, widRaw := range widgetIDs {
					wid, ok := widRaw.(string)
					if !ok {
						continue
					}
					body := widgetBody(topWidgets, wid)

					if html := stringField(body, "html"); strings.TrimSpace(html) != "" {
						lower := strings.ToLower(html)
						skip := false
						for _, p := range systemPhrasesContent {
							if strings.Contains(lower, p) {
								skip = true
								break
							}
						}
						if skip {
							continue
						}
						htmlParts = append(htmlParts, html)
						sectionsOut = append(sectionsOut, model.ContentSection{Type: "rich_text", HTML: html})
						continue
					}

					if btnText := stringField(body, "text"); btnText != "" {
						bg := stringField(body, "background_color")
						if bg == "" {
							bg = "#04c0da"
						}
						sectionsOut = append(sectionsOut, model.ContentSection{
							Type: "button", Text: btnText, BackgroundColor: bg,
							Destination: stringifyDestination(body["destination"]),
						})
						continue
					}

					if img, ok := body["img"].(map[string]any); ok {
						if src := stringField(img, "src"); src != "" {
							sectionsOut = append(sectionsOut, model.ContentSection{Type: "image", Src: src, Alt: stringField(img, "alt")})
							continue
						}
					}

					if lineType := stringField(body, "line_type"); lineType != "" {
						height := 1
						if h, ok := body["height"].(float64); ok {
							height = int(h)
						}
						sectionsOut = append(sectionsOut, model.ContentSection{Type: "divider", Style: lineType, Height: height})
						continue
					}

					if social, ok := body["social"].([]any); ok && len(social) > 0 {
						var nets []string
						for _, sRaw := range social {
							s, _ := sRaw.(map[string]any)
							nets = append(nets, stringField(s, "network"))
						}
						sectionsOut = append(sectionsOut, model.ContentSection{Type: "social_icons", Networks: nets})
					}
				}
			}
		}
	}

	bodyHTML := strings.Join(nonEmptyStrings(htmlParts), "\n\n")
	if len(bodyHTML) > 12000 {
		bodyHTML = bodyHTML[:12000]
	}
	bodyText := stripHTMLBlocks(htmlParts)
	if len(bodyText) > 4000 {
		bodyText = bodyText[:4000]
	}

	return &model.EmailContentText{
		Success: true, EmailID: emailID, EmailName: name, Subject: subject,
		PreviewText: previewText, BodyText: bodyText, BodyHTML: bodyHTML, Sections: sectionsOut,
	}, nil
}

func nonEmptyStrings(parts []string) []string {
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if strings.TrimSpace(p) != "" {
			out = append(out, p)
		}
	}
	return out
}

var bodyTagRe = regexp.MustCompile(`(?is)<body[^>]*>([\s\S]*?)</body\s*>`)

func extractBodyInner(html string) string {
	if m := bodyTagRe.FindStringSubmatch(html); m != nil {
		return strings.TrimSpace(m[1])
	}
	return strings.TrimSpace(html)
}

func utmLinkOrEmpty(eventURL string, utmParams map[string]string, content string) string {
	if eventURL == "" {
		return ""
	}
	return utmtools.AddUTM(eventURL, utmParams, content)
}

func colWidths(n int) []int {
	if n <= 0 {
		return nil
	}
	base, rem := 12/n, 12%n
	out := make([]int, n)
	for i := 0; i < n; i++ {
		out[i] = base
		if i < rem {
			out[i]++
		}
	}
	return out
}

var contentSectionStyle = map[string]any{
	"backgroundType":   "CONTENT",
	"breakpointStyles": map[string]any{"default": map[string]any{"backgroundType": "CONTENT"}},
}

// UpdateEmailContent ports update_email_content — the DnD widget/flexArea
// content writer, including its hardcoded HubSpot module IDs (banner/sponsor
// images: 1367093; rich_text: 1155639 @hubspot/rich_text; button: 1976948;
// footer divider: 2191110 @hubspot/email_divider; social icons: 2763545
// @hubspot/follow_me_email; native footer: 2869621 @hubspot/email_footer).
func (c *HubSpotClient) UpdateEmailContent(ctx context.Context, emailID string, input domain.UpdateEmailContentInput) (*model.UpdateEmailContentResult, error) {
	var email map[string]any
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails/"+emailID, nil, nil, &email); err != nil {
		return nil, err
	}
	content, _ := email["content"].(map[string]any)
	if content == nil {
		content = map[string]any{}
	}

	currentFlex, _ := content["flexAreas"].(map[string]any)
	flexAreaName := "main"
	for k := range currentFlex {
		flexAreaName = k
		break
	}
	styleSettings, _ := content["styleSettings"].(map[string]any)

	innerHTML := extractBodyInner(input.HTMLContent)

	var previewTextWidget any
	if tw, ok := content["widgets"].(map[string]any); ok {
		previewTextWidget = tw["preview_text"]
	}

	widgets := map[string]any{}
	var sections []map[string]any

	if input.BannerURL != "" {
		widgets["staging_banner"] = map[string]any{
			"type": "module", "module_id": 1367093,
			"body": map[string]any{
				"module_id": 1367093,
				"img": map[string]any{
					"src": input.BannerURL, "alt": "Email Banner", "width": 600,
				},
				"link":                      utmLinkOrEmpty(input.EventURL, input.UTMParams, "banner"),
				"stretch_on_mobile":         true,
				"hs_enable_module_padding":  false,
				"hs_wrapper_css": map[string]any{
					"padding-top": "0px", "padding-bottom": "0px",
					"padding-left": "0px", "padding-right": "0px",
				},
			},
		}
		sections = append(sections, map[string]any{
			"id": "section-staging-banner",
			"columns": []map[string]any{
				{"id": "col-banner-0", "widgets": []string{"staging_banner"}, "width": 12},
			},
			"style": map[string]any{
				"backgroundImageType": "REPEAT",
				"backgroundType":      "CONTENT",
				"breakpointStyles": map[string]any{
					"default": map[string]any{"backgroundImageType": "REPEAT", "backgroundType": "CONTENT"},
					"mobile":  map[string]any{},
				},
				"paddingBottom": "0px",
				"paddingTop":    "0px",
			},
		})
	}

	if len(input.ContentSections) > 0 {
		for idx, sec := range input.ContentSections {
			switch sec.Type {
			case "rich_text":
				wid := fmt.Sprintf("staging_sec_%d", idx)
				widgets[wid] = map[string]any{
					"type": "module",
					"body": map[string]any{
						"path": "@hubspot/rich_text", "module_id": 1155639,
						"html":                     utmtools.TagHTMLLinks(sec.HTML, input.UTMParams, "body-link"),
						"hs_enable_module_padding": true,
						"hs_wrapper_css": map[string]any{
							"padding-bottom": "10px", "padding-left": "20px",
							"padding-right": "20px", "padding-top": "15px",
						},
					},
				}
				sections = append(sections, map[string]any{
					"id": fmt.Sprintf("section-sec-%d", idx),
					"columns": []map[string]any{
						{"id": fmt.Sprintf("col-sec-%d-0", idx), "widgets": []string{wid}, "width": 12},
					},
					"style": contentSectionStyle,
				})
			case "button":
				btnColor := sec.Color
				if btnColor == "" {
					btnColor = "#04c0da"
				}
				btnText := sec.Text
				if btnText == "" {
					btnText = "Register Now"
				}
				destURL := sec.URL
				if destURL == "" {
					destURL = "#"
				}
				wid := fmt.Sprintf("staging_btn_%d", idx)
				widgets[wid] = map[string]any{
					"type": "module",
					"body": map[string]any{
						"module_id":        1976948,
						"background_color": btnColor,
						"corner_radius":    8,
						"destination":      utmtools.AddUTM(destURL, input.UTMParams, utmtools.SlugifyUTMContent(btnText, "cta")),
						"font":             "Arial, sans-serif",
						"font_color":       "#ffffff",
						"font_size":        16,
						"font_style": map[string]any{
							"color": "#ffffff", "font": "Arial, sans-serif",
							"size":   map[string]any{"units": "px", "value": 16},
							"styles": map[string]any{"bold": true, "font-weight": "bold", "italic": false, "underline": false},
						},
						"text":                     btnText,
						"hs_enable_module_padding": true,
						"hs_wrapper_css": map[string]any{
							"padding-bottom": "5px", "padding-left": "20px",
							"padding-right": "20px", "padding-top": "5px",
						},
					},
				}
				sections = append(sections, map[string]any{
					"id": fmt.Sprintf("section-btn-%d", idx),
					"columns": []map[string]any{
						{"id": fmt.Sprintf("col-btn-%d-0", idx), "widgets": []string{wid}, "width": 12},
					},
					"style": contentSectionStyle,
				})
			}
		}

		logoSponsors := make([]model.ScrapedSponsor, 0, len(input.Sponsors))
		for _, s := range input.Sponsors {
			if s.LogoURL != "" {
				logoSponsors = append(logoSponsors, s)
			}
		}
		const perTier = 5
		tier1 := logoSponsors
		if len(tier1) > perTier {
			tier1 = tier1[:perTier]
		}
		var tier2 []model.ScrapedSponsor
		if len(logoSponsors) > perTier {
			end := perTier * 2
			if end > len(logoSponsors) {
				end = len(logoSponsors)
			}
			tier2 = logoSponsors[perTier:end]
		}

		chunkRows := func(items []model.ScrapedSponsor) [][]model.ScrapedSponsor {
			if len(items) > perTier {
				items = items[:perTier]
			}
			if len(items) > 3 {
				return [][]model.ScrapedSponsor{items[:3], items[3:5]}
			}
			return [][]model.ScrapedSponsor{items}
		}

		addSponsorTier := func(tierItems []model.ScrapedSponsor, tierKey string, height, width int, pad string) {
			for r, row := range chunkRows(tierItems) {
				widths := colWidths(len(row))
				var cols []map[string]any
				for j, sp := range row {
					wid := fmt.Sprintf("staging_sponsor_%s_%d_%d", tierKey, r, j)
					alt := sp.Name
					if alt == "" {
						alt = "Sponsor"
					}
					widgets[wid] = map[string]any{
						"type": "module",
						"body": map[string]any{
							"module_id": 1367093,
							"img": map[string]any{
								"alt": alt, "height": height, "loading": "disabled",
								"src": sp.LogoURL, "width": width,
							},
							"link":                     "",
							"hs_enable_module_padding": true,
							"hs_wrapper_css": map[string]any{
								"padding-bottom": pad, "padding-left": pad,
								"padding-right": pad, "padding-top": pad,
							},
						},
					}
					cols = append(cols, map[string]any{
						"id": fmt.Sprintf("col-sp-%s-%d-%d", tierKey, r, j),
						"widgets": []string{wid}, "width": widths[j],
					})
				}
				sections = append(sections, map[string]any{
					"id": fmt.Sprintf("section-sponsor-%s-row%d", tierKey, r), "columns": cols, "style": contentSectionStyle,
				})
			}
		}

		if len(tier1) > 0 {
			widgets["staging_sponsor_header"] = map[string]any{
				"type": "module",
				"body": map[string]any{
					"path": "@hubspot/rich_text", "module_id": 1155639,
					"html":                     `<p style="font-weight:bold;text-align:center;font-size:18px;line-height:175%;">Thank You to Our Sponsors!</p>`,
					"hs_enable_module_padding": true,
					"hs_wrapper_css": map[string]any{
						"padding-bottom": "10px", "padding-left": "20px",
						"padding-right": "20px", "padding-top": "10px",
					},
				},
			}
			sections = append(sections, map[string]any{
				"id": "section-sponsor-header",
				"columns": []map[string]any{
					{"id": "col-sph-0", "widgets": []string{"staging_sponsor_header"}, "width": 12},
				},
				"style": contentSectionStyle,
			})
			addSponsorTier(tier1, "t1", 60, 180, "15px")
			addSponsorTier(tier2, "t2", 45, 140, "10px")
		}
	} else {
		widgets["staging_body"] = map[string]any{
			"type": "module",
			"body": map[string]any{
				"path": "@hubspot/rich_text", "schema_version": 2,
				"html": utmtools.TagHTMLLinks(innerHTML, input.UTMParams, "body-link"),
			},
		}
		sections = append(sections, map[string]any{
			"id": "section-staging-body",
			"columns": []map[string]any{
				{"id": "col-body-0", "widgets": []string{"staging_body"}, "width": 12},
			},
			"style": contentSectionStyle,
		})
	}

	// Footer — divider, "FOLLOW US" heading, social icons, "sent by" text,
	// native HubSpot footer. Order and module IDs mirror published LF emails.
	widgets["staging_footer_divider"] = map[string]any{
		"type": "module",
		"body": map[string]any{
			"path": "@hubspot/email_divider", "module_id": 2191110,
			"line_type": "solid",
			"color":     map[string]any{"color": "#000000", "opacity": 100},
			"height":    1, "width": 100,
			"hs_enable_module_padding": true,
			"hs_wrapper_css": map[string]any{
				"padding-bottom": "10px", "padding-left": "20px",
				"padding-right": "20px", "padding-top": "5px",
			},
		},
	}
	sections = append(sections, map[string]any{
		"id": "section-footer-divider",
		"columns": []map[string]any{
			{"id": "col-footer-div-0", "widgets": []string{"staging_footer_divider"}, "width": 12},
		},
		"style": contentSectionStyle,
	})

	widgets["staging_footer_follow_header"] = map[string]any{
		"type": "module",
		"body": map[string]any{
			"path": "@hubspot/rich_text", "module_id": 1155639,
			"html":                     `<p style="font-weight: bold; text-align: center;">FOLLOW US</p>`,
			"hs_enable_module_padding": false,
			"hs_wrapper_css":           map[string]any{},
		},
	}
	sections = append(sections, map[string]any{
		"id": "section-footer-follow-header",
		"columns": []map[string]any{
			{"id": "col-footer-fhdr-0", "widgets": []string{"staging_footer_follow_header"}, "width": 12},
		},
		"style": contentSectionStyle,
	})

	widgets["staging_footer_social"] = map[string]any{
		"type": "module",
		"body": map[string]any{
			"path": "@hubspot/follow_me_email", "module_id": 2763545,
			"color_scheme": "black", "icon_shape": "circle",
			"font_style": map[string]any{
				"color": "#000000", "font": "Helvetica,Arial,sans-serif",
				"size":   map[string]any{"units": "px", "value": 14},
				"styles": map[string]any{"bold": true, "italic": false, "underline": false},
			},
			"hs_enable_module_padding": false,
			"hs_wrapper_css":           map[string]any{},
			"social": []map[string]any{
				{
					"network": "icon",
					"network_image": map[string]any{
						"alt": "LFX Insights", "height": 675,
						"src":   "https://8112310.fs1.hubspotusercontent-na1.net/hubfs/8112310/LFX%20Logo%20-%20white%20-%203-1.png",
						"width": 1536,
					},
					"url": utmtools.AddUTM(
						"https://insights.linuxfoundation.org/?utm_campaign=23551824-Q3-2025-LF-Awareness-LFX-Insights&utm_source=email&utm_medium=LF-Events&utm_content=regular-email",
						input.UTMParams, "social-lfx-insights",
					),
				},
				{"network": "twitter", "url": utmtools.AddUTM("https://twitter.com/linuxfoundation", input.UTMParams, "social-twitter")},
				{"network": "linkedin", "url": utmtools.AddUTM("https://www.linkedin.com/company/the-linux-foundation/", input.UTMParams, "social-linkedin")},
				{"network": "youtube", "url": utmtools.AddUTM("https://www.youtube.com/user/TheLinuxFoundation", input.UTMParams, "social-youtube")},
				{"network": "facebook", "url": utmtools.AddUTM("https://www.facebook.com/TheLinuxFoundation/", input.UTMParams, "social-facebook")},
			},
		},
	}
	sections = append(sections, map[string]any{
		"id": "section-footer-social",
		"columns": []map[string]any{
			{"id": "col-footer-soc-0", "widgets": []string{"staging_footer_social"}, "width": 12},
		},
		"style": contentSectionStyle,
	})

	sentByOrg := input.SentByOrg
	if sentByOrg == "" {
		sentByOrg = "The Linux Foundation Events"
	}
	widgets["staging_footer_body"] = map[string]any{
		"type": "module",
		"body": map[string]any{
			"path": "@hubspot/rich_text", "module_id": 1155639,
			"html": fmt.Sprintf(
				`<h2 style="font-size:8px;line-height:175%%;font-weight:normal;text-align:center;"><span style="font-size:12px;color:#000000;">This email was sent by: <span style="font-weight:normal;">%s</span></span></h2>`,
				sentByOrg,
			),
			"hs_enable_module_padding": true,
			"hs_wrapper_css": map[string]any{
				"padding-bottom": "0px", "padding-left": "20px",
				"padding-right": "20px", "padding-top": "0px",
			},
		},
	}
	sections = append(sections, map[string]any{
		"id": "section-footer-body",
		"columns": []map[string]any{
			{"id": "col-footer-body-0", "widgets": []string{"staging_footer_body"}, "width": 12},
		},
		"style": contentSectionStyle,
	})

	widgets["staging_footer_hs"] = map[string]any{
		"type": "module",
		"body": map[string]any{
			"path": "@hubspot/email_footer", "module_id": 2869621,
			"font": map[string]any{
				"color": "#000000", "font": "Arial, sans-serif",
				"size":   map[string]any{"units": "px", "value": 12},
				"styles": map[string]any{"bold": false, "italic": false, "underline": false},
			},
			"link_font": map[string]any{
				"color": "#0094ff", "font": "Arial, sans-serif", "font_set": "DEFAULT",
				"size":   map[string]any{"units": "px", "value": 12},
				"styles": map[string]any{"bold": false, "italic": false, "underline": true},
			},
			"hs_enable_module_padding": false,
			"hs_wrapper_css":           map[string]any{},
		},
	}
	sections = append(sections, map[string]any{
		"id": "section-footer-hs",
		"columns": []map[string]any{
			{"id": "col-footer-hs-0", "widgets": []string{"staging_footer_hs"}, "width": 12},
		},
		"style": contentSectionStyle,
	})

	if previewTextWidget != nil {
		widgets["preview_text"] = previewTextWidget
	}

	newFlexAreas := map[string]any{
		flexAreaName: map[string]any{
			"boxed": false, "isSingleColumnFullWidth": false, "sections": sections,
		},
	}
	newContent := map[string]any{
		"templatePath": "@hubspot/email/dnd/Start_from_scratch.html",
		"widgets":      widgets,
		"flexAreas":    newFlexAreas,
	}
	if styleSettings != nil {
		newContent["styleSettings"] = styleSettings
	}

	if err := c.request(ctx, http.MethodPatch, "/marketing/v3/emails/"+emailID, nil, map[string]any{"content": newContent}, nil); err != nil {
		return nil, err
	}

	// Verify HubSpot actually persisted our widgets (not a silent revert).
	var verify map[string]any
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails/"+emailID, nil, nil, &verify); err != nil {
		return nil, fmt.Errorf("verify content update for email %s: %w", emailID, err)
	}
	verifyContent, _ := verify["content"].(map[string]any)
	savedFlex, _ := verifyContent["flexAreas"].(map[string]any)
	savedArea, _ := savedFlex[flexAreaName].(map[string]any)
	savedSections, _ := savedArea["sections"].([]any)

	savedWidgetKeys := map[string]struct{}{}
	for _, secRaw := range savedSections {
		sec, _ := secRaw.(map[string]any)
		cols, _ := sec["columns"].([]any)
		for _, colRaw := range cols {
			col, _ := colRaw.(map[string]any)
			ws, _ := col["widgets"].([]any)
			for _, wRaw := range ws {
				if w, ok := wRaw.(string); ok {
					savedWidgetKeys[w] = struct{}{}
				}
			}
		}
	}

	ourWidgetKeys := make([]string, 0, len(widgets))
	for k := range widgets {
		if k != "preview_text" {
			ourWidgetKeys = append(ourWidgetKeys, k)
		}
	}
	overlap := 0
	for _, k := range ourWidgetKeys {
		if _, ok := savedWidgetKeys[k]; ok {
			overlap++
		}
	}

	if len(ourWidgetKeys) > 0 && overlap == 0 {
		sort.Strings(ourWidgetKeys)
		savedList := make([]string, 0, len(savedWidgetKeys))
		for k := range savedWidgetKeys {
			savedList = append(savedList, k)
		}
		sort.Strings(savedList)
		expected, found := ourWidgetKeys, savedList
		if len(expected) > 3 {
			expected = expected[:3]
		}
		if len(found) > 3 {
			found = found[:3]
		}
		return &model.UpdateEmailContentResult{
			Success: false, EmailID: emailID,
			Error: fmt.Sprintf(
				"HubSpot accepted the PATCH but did not save our widgets. The email template may not support dynamic flex areas. Expected widgets: %v, found: %v",
				expected, found,
			),
		}, nil
	}

	var method string
	switch {
	case len(input.ContentSections) > 0:
		method = fmt.Sprintf("structured(%d sections, %d sponsors)", len(input.ContentSections), len(input.Sponsors))
	case input.BannerURL != "":
		method = "image+rich_text"
	default:
		method = "rich_text_only"
	}

	return &model.UpdateEmailContentResult{Success: true, EmailID: emailID, Method: method}, nil
}

// systemPhrasesValidate is the (smaller, distinct) system-text list checked
// by ValidateStagedEmail — ports validate_staged_email's _system_phrases.
var systemPhrasesValidate = []string{
	"view in browser", "view this email", "unsubscribe",
	"subscription center", "2810 n church", "wilmington, delaware",
}

// ValidateStagedEmail ports validate_staged_email.
func (c *HubSpotClient) ValidateStagedEmail(ctx context.Context, emailID string, expectBanner bool, expectSections int) (*model.ValidateStagedEmailResult, error) {
	var email map[string]any
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails/"+emailID, nil, nil, &email); err != nil {
		msg := fmt.Sprintf("Failed to fetch email: %s", err.Error())
		return &model.ValidateStagedEmailResult{Valid: false, Issues: []string{msg}, Summary: err.Error()}, nil
	}
	content, _ := email["content"].(map[string]any)

	var issues []string

	subject := strings.TrimSpace(stringField(email, "subject"))
	fromAddr := strings.TrimSpace(stringField(email, "fromEmail"))
	if fromAddr == "" {
		if rss, ok := email["rssData"].(map[string]any); ok {
			fromAddr = strings.TrimSpace(stringField(rss, "fromEmail"))
		}
	}
	if subject == "" {
		issues = append(issues, "Subject line is empty")
	}
	if fromAddr == "" {
		issues = append(issues, "From address is missing")
	}

	topWidgets, _ := content["widgets"].(map[string]any)
	if topWidgets == nil {
		topWidgets = map[string]any{}
	}
	flexAreas, _ := content["flexAreas"].(map[string]any)

	var referenced []string
	for _, areaRaw := range flexAreas {
		area, _ := areaRaw.(map[string]any)
		sections, _ := area["sections"].([]any)
		for _, secRaw := range sections {
			sec, _ := secRaw.(map[string]any)
			cols, _ := sec["columns"].([]any)
			for _, colRaw := range cols {
				col, _ := colRaw.(map[string]any)
				ws, _ := col["widgets"].([]any)
				for _, wRaw := range ws {
					if w, ok := wRaw.(string); ok {
						referenced = append(referenced, w)
					}
				}
			}
		}
	}

	if len(referenced) == 0 {
		issues = append(issues, "flexAreas contain no widget references — content was not saved")
		return &model.ValidateStagedEmailResult{Valid: false, Issues: issues, Summary: strings.Join(issues, "; ")}, nil
	}

	if expectBanner {
		hasBanner := false
		for _, w := range referenced {
			if _, ok := widgetBody(topWidgets, w)["img"]; ok {
				hasBanner = true
				break
			}
		}
		if !hasBanner {
			issues = append(issues, "Banner image widget is missing from email")
		}
	}

	richTextCount := 0
	for _, w := range referenced {
		html := stringField(widgetBody(topWidgets, w), "html")
		if html == "" {
			continue
		}
		lower := strings.ToLower(html)
		for _, phrase := range systemPhrasesValidate {
			if strings.Contains(lower, phrase) {
				issues = append(issues, fmt.Sprintf(`Widget "%s" contains system text: "%s"`, w, phrase))
				break
			}
		}
		if strings.TrimSpace(anyTagRe.ReplaceAllString(html, "")) != "" {
			richTextCount++
		}
	}
	if richTextCount < expectSections {
		issues = append(issues, fmt.Sprintf(
			"Expected at least %d content section(s) with text, found %d", expectSections, richTextCount,
		))
	}

	hasHSFooter, hasSocial, hasDivider := false, false, false
	for _, w := range referenced {
		path := stringField(widgetBody(topWidgets, w), "path")
		if strings.Contains(path, "email_footer") {
			hasHSFooter = true
		}
		if strings.Contains(path, "follow_me") {
			hasSocial = true
		}
		if strings.Contains(path, "email_divider") {
			hasDivider = true
		}
	}
	if !hasHSFooter {
		issues = append(issues, "HubSpot email footer module (unsubscribe/address) is missing")
	}
	if !hasSocial {
		issues = append(issues, "Social icons footer is missing")
	}
	if !hasDivider {
		issues = append(issues, "Footer divider is missing")
	}

	footerStatus := "MISSING"
	if hasHSFooter {
		footerStatus = "ok"
	}
	bannerStatus := "n/a"
	if expectBanner {
		bannerStatus = "yes"
	}
	summary := fmt.Sprintf(
		"Validated %d widget(s): %d text section(s), banner=%s, footer=%s",
		len(referenced), richTextCount, bannerStatus, footerStatus,
	)

	return &model.ValidateStagedEmailResult{Valid: len(issues) == 0, Issues: issues, Summary: summary}, nil
}

// UploadImageToHubSpot ports upload_image_to_hubspot. Never returns an
// error — any download/upload failure yields ("", nil), matching Python's
// "return empty string on failure" contract.
func (c *HubSpotClient) UploadImageToHubSpot(ctx context.Context, imageURL, filename string) (string, error) {
	if imageURL == "" || c.token == "" {
		return "", nil
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, imageURL, nil)
	if err != nil {
		return "", nil
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", nil
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", nil
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", nil
	}

	contentType := resp.Header.Get("Content-Type")
	if idx := strings.Index(contentType, ";"); idx >= 0 {
		contentType = contentType[:idx]
	}
	contentType = strings.TrimSpace(contentType)
	if contentType == "" {
		contentType = "image/jpeg"
	}
	if !strings.HasPrefix(contentType, "image/") {
		return "", nil
	}

	if filename == "" {
		raw := ""
		if u, err := url.Parse(imageURL); err == nil {
			parts := strings.Split(strings.TrimSuffix(u.Path, "/"), "/")
			raw = parts[len(parts)-1]
			if idx := strings.Index(raw, "?"); idx >= 0 {
				raw = raw[:idx]
			}
		}
		if raw == "" || !strings.Contains(raw, ".") {
			ext := strings.Replace(strings.TrimPrefix(contentType, "image/"), "jpeg", "jpg", 1)
			if ext == "" {
				ext = "jpg"
			}
			raw = "email_img." + ext
		}
		if len(raw) > 80 {
			raw = raw[:80]
		}
		filename = raw
	}

	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	part, err := mw.CreateFormFile("file", filename)
	if err != nil {
		return "", nil
	}
	if _, err := part.Write(data); err != nil {
		return "", nil
	}
	_ = mw.WriteField("options", `{"access":"PUBLIC_INDEXABLE","overwrite":true}`)
	_ = mw.WriteField("folderPath", "/email-staging")
	if err := mw.Close(); err != nil {
		return "", nil
	}

	uploadReq, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.hubapi.com/files/v3/files", &buf)
	if err != nil {
		return "", nil
	}
	uploadReq.Header.Set("Authorization", "Bearer "+c.token)
	uploadReq.Header.Set("Content-Type", mw.FormDataContentType())

	uploadResp, err := c.httpClient.Do(uploadReq)
	if err != nil {
		return "", nil
	}
	defer uploadResp.Body.Close()
	if uploadResp.StatusCode < 200 || uploadResp.StatusCode >= 300 {
		return "", nil
	}

	var out struct {
		URL string `json:"url"`
	}
	if err := json.NewDecoder(uploadResp.Body).Decode(&out); err != nil {
		return "", nil
	}
	return out.URL, nil
}
