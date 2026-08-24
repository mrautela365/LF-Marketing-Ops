package dispatch

import (
	"context"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/utmtools"
)

// ResolveUTMCampaign ports resolve_utm_campaign. It reuses GetCampaign +
// GetCampaignUTM (no separate HTTP calls needed) and never returns an error
// — any lookup failure just falls through to the fallback slug, matching
// Python's swallow-and-fallback behavior.
func (c *HubSpotClient) ResolveUTMCampaign(ctx context.Context, sourceEmailID, fallbackName string) (*model.UTMResolution, error) {
	fallbackSlug := utmtools.SlugifyUTMContent(fallbackName, "")

	var campaignID, campaignName, utmCampaign string

	if sourceEmailID != "" {
		if guid, name, err := c.GetCampaign(ctx, sourceEmailID); err == nil {
			campaignID, campaignName = guid, name
			if campaignID != "" {
				if utm, err := c.GetCampaignUTM(ctx, campaignID); err == nil {
					if utm.Name != "" {
						campaignName = utm.Name
					}
					utmCampaign = utm.UTM
				}
			}
		}
	}

	source := "hubspot_campaign"
	if utmCampaign == "" {
		if fallbackSlug != "" {
			utmCampaign = fallbackSlug
		} else {
			utmCampaign = "email-campaign"
		}
		source = "fallback"
	}

	return &model.UTMResolution{
		CampaignID:   campaignID,
		CampaignName: campaignName,
		UTMCampaign:  utmCampaign,
		Source:       source,
		UTMSource:    "email",
		UTMMedium:    "LF-Events",
	}, nil
}
