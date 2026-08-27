package audience

import (
	"context"
	"strings"
	"testing"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

func TestBuildInListOrBranch(t *testing.T) {
	t.Run("single id", func(t *testing.T) {
		branch := BuildInListOrBranch([]string{"123"})
		if branch.FilterBranchType != "OR" || len(branch.FilterBranches) != 1 {
			t.Fatalf("got %+v", branch)
		}
		and := branch.FilterBranches[0]
		if and.FilterBranchType != "AND" {
			t.Fatalf("got %+v", and)
		}
		if len(and.Filters) != 1 || and.Filters[0] != (model.Filter{FilterType: "IN_LIST", ListID: "123", Operator: "IN_LIST"}) {
			t.Fatalf("got %+v", and.Filters)
		}
	})

	t.Run("multiple ids preserve order", func(t *testing.T) {
		branch := BuildInListOrBranch([]string{"111", "222", "333"})
		var ids []string
		for _, b := range branch.FilterBranches {
			ids = append(ids, b.Filters[0].ListID)
		}
		if strings.Join(ids, ",") != "111,222,333" {
			t.Fatalf("got %v", ids)
		}
	})

	t.Run("dedup", func(t *testing.T) {
		branch := BuildInListOrBranch([]string{"111", "222", "111", "222"})
		var ids []string
		for _, b := range branch.FilterBranches {
			ids = append(ids, b.Filters[0].ListID)
		}
		if strings.Join(ids, ",") != "111,222" {
			t.Fatalf("got %v", ids)
		}
	})

	t.Run("blank and whitespace ids skipped", func(t *testing.T) {
		branch := BuildInListOrBranch([]string{"111", "", "  ", "222"})
		var ids []string
		for _, b := range branch.FilterBranches {
			ids = append(ids, b.Filters[0].ListID)
		}
		if strings.Join(ids, ",") != "111,222" {
			t.Fatalf("got %v", ids)
		}
	})

	t.Run("empty input", func(t *testing.T) {
		branch := BuildInListOrBranch([]string{})
		if len(branch.FilterBranches) != 0 {
			t.Fatalf("got %+v", branch.FilterBranches)
		}
	})
}

func TestBuildMasterListName(t *testing.T) {
	cases := []struct {
		name       string
		brandShort string
		eventName  string
		eventDates []string
		want       string
		wantSuffix string
	}{
		{name: "with brand and event", brandShort: "CNCF", eventName: "KubeCon NA", eventDates: []string{"2026-08-15"}, want: "26Q3 - CNCF - KubeCon NA - Master"},
		{name: "missing brand no double dash", eventName: "KubeCon NA", eventDates: []string{"2026-08-15"}, want: "26Q3 - KubeCon NA - Master"},
		{name: "missing event no double dash", brandShort: "CNCF", eventDates: []string{"2026-08-15"}, want: "26Q3 - CNCF - Master"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := BuildMasterListName("", tc.brandShort, tc.eventName, tc.eventDates, "Master")
			if got != tc.want {
				t.Fatalf("got %q want %q", got, tc.want)
			}
			if strings.Contains(got, " -  - ") {
				t.Fatalf("double dash in %q", got)
			}
		})
	}

	t.Run("quarter boundaries", func(t *testing.T) {
		q1 := BuildMasterListName("", "LF", "Event", []string{"2026-01-01"}, "Master")
		if !strings.HasPrefix(q1, "26Q1") {
			t.Fatalf("got %q", q1)
		}
		q2 := BuildMasterListName("", "LF", "Event", []string{"2026-04-01"}, "Master")
		if !strings.HasPrefix(q2, "26Q2") {
			t.Fatalf("got %q", q2)
		}
		q4 := BuildMasterListName("", "LF", "Event", []string{"2026-12-31"}, "Master")
		if !strings.HasPrefix(q4, "26Q4") {
			t.Fatalf("got %q", q4)
		}
	})

	t.Run("no dates falls back to today quarter", func(t *testing.T) {
		name := BuildMasterListName("", "CNCF", "KubeCon NA", nil, "Master")
		if !strings.HasSuffix(name, "CNCF - KubeCon NA - Master") {
			t.Fatalf("got %q", name)
		}
		if name[2] != 'Q' {
			t.Fatalf("got %q", name)
		}
	})

	t.Run("nothing provided still returns generic name", func(t *testing.T) {
		name := BuildMasterListName("", "", "", nil, "Master")
		if !strings.HasSuffix(name, "Audience - Master") {
			t.Fatalf("got %q", name)
		}
		if name[2] != 'Q' {
			t.Fatalf("got %q", name)
		}
	})
}

// fakeListClient is a minimal in-memory domain.HubSpotListClient fake for
// service-level tests — only CreateList is exercised by these tests.
type fakeListClient struct {
	createCalls   []string
	createResults []*model.CreatedList
	createErrs    []error
}

func (f *fakeListClient) SearchLists(ctx context.Context, query string, limit int) ([]model.ListInfo, error) {
	return nil, nil
}
func (f *fakeListClient) SearchListsByName(ctx context.Context, query string, limit int) ([]model.ListInfo, error) {
	return nil, nil
}
func (f *fakeListClient) GetList(ctx context.Context, listID string) (*model.ListInfo, error) {
	return nil, nil
}
func (f *fakeListClient) GetListProcessingType(ctx context.Context, listID string) (string, error) {
	return "", nil
}
func (f *fakeListClient) IsILSList(ctx context.Context, listID string) (bool, error) {
	return false, nil
}
func (f *fakeListClient) ListMembershipIDs(ctx context.Context, listID string, capPages int) ([]string, error) {
	return nil, nil
}
func (f *fakeListClient) CreateList(ctx context.Context, name string, filterBranch model.FilterBranch) (*model.CreatedList, error) {
	i := len(f.createCalls)
	f.createCalls = append(f.createCalls, name)
	if i < len(f.createErrs) && f.createErrs[i] != nil {
		return nil, f.createErrs[i]
	}
	if i < len(f.createResults) {
		return f.createResults[i], nil
	}
	return &model.CreatedList{ListID: "999", Name: name}, nil
}
func (f *fakeListClient) UpdateListFilters(ctx context.Context, listID string, filterBranch model.FilterBranch) error {
	return nil
}
func (f *fakeListClient) GetEventTypes(ctx context.Context) ([]model.EventTypeDef, error) {
	return nil, nil
}
func (f *fakeListClient) GetLegacyListName(ctx context.Context, listID string) (string, bool, error) {
	return "", false, nil
}

func TestComposeMasterListFromIDs_RetriesWithTimestampOnNameCollision(t *testing.T) {
	fake := &fakeListClient{
		createErrs:    []error{errAlreadyExists, nil},
		createResults: []*model.CreatedList{nil, {ListID: "999", Name: "placeholder", Size: 42, HubSpotURL: "https://example.com"}},
	}
	svc := NewMasterListService(fake, "8112310")

	result, err := svc.ComposeMasterListFromIDs(context.Background(), []string{"111", "222"}, "Existing Name", "", "", "", nil, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(fake.createCalls) != 2 {
		t.Fatalf("expected 2 create calls, got %d: %v", len(fake.createCalls), fake.createCalls)
	}
	if fake.createCalls[0] != "Existing Name" {
		t.Fatalf("got %q", fake.createCalls[0])
	}
	if fake.createCalls[1] == "Existing Name" || !strings.HasPrefix(fake.createCalls[1], "Existing Name (") {
		t.Fatalf("got %q", fake.createCalls[1])
	}
	if result.ListID != "999" {
		t.Fatalf("got %+v", result)
	}
}

func TestComposeMasterListFromIDs_ReraisesNonCollisionErrors(t *testing.T) {
	fake := &fakeListClient{createErrs: []error{errInternal}}
	svc := NewMasterListService(fake, "8112310")

	_, err := svc.ComposeMasterListFromIDs(context.Background(), []string{"111"}, "Whatever", "", "", "", nil, nil)
	if err == nil || !strings.Contains(err.Error(), "internal error") {
		t.Fatalf("expected internal error, got %v", err)
	}
}

var errAlreadyExists = &testError{"HubSpot 400: a list with this name already exists"}
var errInternal = &testError{"HubSpot 500: internal error"}

type testError struct{ msg string }

func (e *testError) Error() string { return e.msg }
