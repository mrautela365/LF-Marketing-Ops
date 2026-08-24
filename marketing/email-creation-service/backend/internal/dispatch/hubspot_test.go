package dispatch

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

func newTestClient(t *testing.T, handler http.HandlerFunc) *HubSpotClient {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	c := NewHubSpotClient("test-token", "8112310", "")
	c.httpClient = srv.Client()
	c.baseURLOverride = srv.URL
	return c
}

func TestSetEmailSendList_RejectsMixedNamespaces(t *testing.T) {
	c := NewHubSpotClient("tok", "8112310", "")
	err := c.SetEmailSendList(context.Background(), "123", domain.SendListUpdate{
		ContactLists:    model.ListIncludeExclude{Include: []string{"1"}},
		ContactIlsLists: model.ListIncludeExclude{Include: []string{"2"}},
	})
	if err == nil {
		t.Fatal("expected error when mixing legacy and ILS namespaces, got nil")
	}
}

func TestSearchLists_HandlesDualIDShapeAndFallbackSize(t *testing.T) {
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/crm/v3/lists/search" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"lists": []map[string]any{
				{"listId": "111", "name": "A", "size": 5, "processingType": "DYNAMIC"},
				{"id": "222", "name": "B", "additionalProperties": map[string]any{"hs_list_size": 9}},
			},
		})
	})

	lists, err := c.SearchLists(context.Background(), "kubecon", 0)
	if err != nil {
		t.Fatalf("SearchLists: %v", err)
	}
	if len(lists) != 2 {
		t.Fatalf("expected 2 lists, got %d", len(lists))
	}
	if lists[0].ID != "111" || lists[0].Size != 5 {
		t.Errorf("list 0 = %+v", lists[0])
	}
	if lists[1].ID != "222" || lists[1].Size != 9 {
		t.Errorf("list 1 (fallback size) = %+v", lists[1])
	}
}

func TestGetListProcessingType_UnwrapsListWrapperAndHandles404(t *testing.T) {
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/crm/v3/lists/known":
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{
				"list": map[string]any{"processingType": "DYNAMIC"},
			})
		case "/crm/v3/lists/legacy":
			w.WriteHeader(http.StatusNotFound)
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	})

	pt, err := c.GetListProcessingType(context.Background(), "known")
	if err != nil || pt != "DYNAMIC" {
		t.Fatalf("known list: pt=%q err=%v", pt, err)
	}
	pt, err = c.GetListProcessingType(context.Background(), "legacy")
	if err != nil || pt != "UNKNOWN" {
		t.Fatalf("legacy list: expected UNKNOWN/nil, got pt=%q err=%v", pt, err)
	}
}
