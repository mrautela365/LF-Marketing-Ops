package filteroptimizer

import (
	"sort"
	"strings"
	"testing"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

func propertyFilter(property, operator string, values []string, includeNoValue bool) model.Filter {
	return model.Filter{
		FilterType: "PROPERTY",
		Property:   property,
		Operation: &model.FilterOperation{
			Operator:                     operator,
			IncludeObjectsWithNoValueSet: includeNoValue,
			Values:                       values,
			OperationType:                "MULTISTRING",
		},
	}
}

func inListFilter(listID string) model.Filter {
	return model.Filter{FilterType: "IN_LIST", ListID: listID, Operator: "IN_LIST"}
}

func andBranch(filters ...model.Filter) model.FilterBranch {
	return model.FilterBranch{FilterBranchType: "AND", Filters: filters}
}

func sortedStrings(vals []string) []string {
	out := append([]string(nil), vals...)
	sort.Strings(out)
	return out
}

func TestOptimize_NoOpSingleBranch(t *testing.T) {
	o := New(false)
	fb := model.FilterBranch{
		FilterBranchType: "OR",
		FilterBranches: []model.FilterBranch{
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"cloud native"}, false)),
		},
	}
	result := o.Optimize(fb)
	if o.Applied() {
		t.Fatal("expected no optimization for a single branch")
	}
	if len(result.FilterBranches) != 1 {
		t.Fatalf("expected 1 branch, got %d", len(result.FilterBranches))
	}
}

func TestOptimize_CombineTwoIdenticalBranches(t *testing.T) {
	o := New(false)
	fb := model.FilterBranch{
		FilterBranchType: "OR",
		FilterBranches: []model.FilterBranch{
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"cloud native"}, false)),
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"kubernetes"}, false)),
		},
	}
	result := o.Optimize(fb)
	if !o.Applied() {
		t.Fatal("expected optimization to apply")
	}
	if len(result.FilterBranches) != 1 {
		t.Fatalf("expected 1 combined branch, got %d", len(result.FilterBranches))
	}
	values := result.FilterBranches[0].Filters[0].Operation.Values
	want := []string{"cloud native", "kubernetes"}
	if strings.Join(sortedStrings(values), ",") != strings.Join(want, ",") {
		t.Errorf("values = %v, want %v", values, want)
	}
}

func TestOptimize_CombineMultipleBranchesWithGate(t *testing.T) {
	o := New(false)
	titles := []string{"cloud native", "kubernetes", "cloud architect", "system administrator"}
	var branches []model.FilterBranch
	for _, title := range titles {
		branches = append(branches, andBranch(
			propertyFilter("jobtitle", "CONTAINS", []string{title}, false),
			inListFilter("26716"),
		))
	}
	fb := model.FilterBranch{FilterBranchType: "OR", FilterBranches: branches}

	result := o.Optimize(fb)
	if !o.Applied() {
		t.Fatal("expected optimization to apply")
	}
	if len(result.FilterBranches) != 1 {
		t.Fatalf("expected 1 branch, got %d", len(result.FilterBranches))
	}
	filters := result.FilterBranches[0].Filters
	if len(filters) != 2 {
		t.Fatalf("expected 2 filters (property + gate), got %d", len(filters))
	}
	var propFilter, listFilter *model.Filter
	for i := range filters {
		switch filters[i].FilterType {
		case "PROPERTY":
			propFilter = &filters[i]
		case "IN_LIST":
			listFilter = &filters[i]
		}
	}
	if propFilter == nil || listFilter == nil {
		t.Fatalf("expected both PROPERTY and IN_LIST filters, got %+v", filters)
	}
	if strings.Join(sortedStrings(propFilter.Operation.Values), ",") != strings.Join(sortedStrings(titles), ",") {
		t.Errorf("job titles = %v, want %v", propFilter.Operation.Values, titles)
	}
	if listFilter.ListID != "26716" {
		t.Errorf("listId = %q, want 26716", listFilter.ListID)
	}
}

func TestOptimize_DeduplicationOfValues(t *testing.T) {
	o := New(false)
	fb := model.FilterBranch{
		FilterBranchType: "OR",
		FilterBranches: []model.FilterBranch{
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"cloud engineer", "kubernetes"}, false)),
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"kubernetes", "devops"}, false)),
		},
	}
	result := o.Optimize(fb)
	if !o.Applied() {
		t.Fatal("expected optimization to apply")
	}
	values := result.FilterBranches[0].Filters[0].Operation.Values
	count := 0
	for _, v := range values {
		if v == "kubernetes" {
			count++
		}
	}
	if count != 1 {
		t.Errorf("expected kubernetes to appear once, got %d times in %v", count, values)
	}
	want := []string{"cloud engineer", "devops", "kubernetes"}
	if strings.Join(sortedStrings(values), ",") != strings.Join(want, ",") {
		t.Errorf("values = %v, want %v", values, want)
	}
}

func TestOptimize_SkipUnifiedEventsNesting(t *testing.T) {
	o := New(false)
	nested := func() model.FilterBranch {
		return andBranch()
	}
	unified := model.FilterBranch{
		FilterBranchType: "UNIFIED_EVENTS",
		Operator:         "HAS_COMPLETED",
		EventTypeID:      "6-58204655",
		Filters: []model.Filter{
			propertyFilter("has_tech_cloud_containers", "IS_ANY_OF", []string{"true"}, false),
		},
	}
	b1 := nested()
	b1.FilterBranches = []model.FilterBranch{unified}
	b2 := nested()
	b2.FilterBranches = []model.FilterBranch{unified}

	fb := model.FilterBranch{FilterBranchType: "OR", FilterBranches: []model.FilterBranch{b1, b2}}
	result := o.Optimize(fb)
	if o.Applied() {
		t.Fatal("expected no optimization for nested UNIFIED_EVENTS branches")
	}
	if len(result.FilterBranches) != 2 {
		t.Fatalf("expected 2 branches preserved, got %d", len(result.FilterBranches))
	}
}

func TestOptimize_SkipIncludeObjectsWithNoValueSetTrue(t *testing.T) {
	o := New(false)
	fb := model.FilterBranch{
		FilterBranchType: "OR",
		FilterBranches: []model.FilterBranch{
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"cloud native"}, true)),
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"kubernetes"}, true)),
		},
	}
	result := o.Optimize(fb)
	if o.Applied() {
		t.Fatal("expected no optimization when includeObjectsWithNoValueSet=true")
	}
	if len(result.FilterBranches) != 2 {
		t.Fatalf("expected 2 branches preserved, got %d", len(result.FilterBranches))
	}
}

func TestOptimize_MixedCombinableAndNonCombinable(t *testing.T) {
	o := New(false)
	fb := model.FilterBranch{
		FilterBranchType: "OR",
		FilterBranches: []model.FilterBranch{
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"cloud native"}, false)),
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"kubernetes"}, false)),
			andBranch(model.Filter{
				FilterType: "PROPERTY",
				Property:   "country",
				Operation: &model.FilterOperation{
					Operator:                     "IS_EQUAL_TO",
					IncludeObjectsWithNoValueSet: false,
					Values:                       []string{"Korea"},
					OperationType:                "STRING",
				},
			}),
		},
	}
	result := o.Optimize(fb)
	if !o.Applied() {
		t.Fatal("expected optimization to apply")
	}
	if len(result.FilterBranches) != 2 {
		t.Fatalf("expected 2 branches (combined + country), got %d", len(result.FilterBranches))
	}
	var jobBranch, countryBranch *model.FilterBranch
	for i := range result.FilterBranches {
		switch result.FilterBranches[i].Filters[0].Property {
		case "jobtitle":
			jobBranch = &result.FilterBranches[i]
		case "country":
			countryBranch = &result.FilterBranches[i]
		}
	}
	if jobBranch == nil || countryBranch == nil {
		t.Fatalf("expected both jobtitle and country branches, got %+v", result.FilterBranches)
	}
	want := []string{"cloud native", "kubernetes"}
	if strings.Join(sortedStrings(jobBranch.Filters[0].Operation.Values), ",") != strings.Join(want, ",") {
		t.Errorf("job titles = %v, want %v", jobBranch.Filters[0].Operation.Values, want)
	}
	if strings.Join(countryBranch.Filters[0].Operation.Values, ",") != "Korea" {
		t.Errorf("country values = %v, want [Korea]", countryBranch.Filters[0].Operation.Values)
	}
}

func TestOptimize_DistinctInListBranchesNeverCollapse(t *testing.T) {
	o := New(false)
	listIDs := []string{"27820", "18319", "19388", "19724", "19571"}
	var branches []model.FilterBranch
	for _, id := range listIDs {
		branches = append(branches, andBranch(inListFilter(id)))
	}
	fb := model.FilterBranch{FilterBranchType: "OR", FilterBranches: branches}

	result := o.Optimize(fb)
	if o.Applied() {
		t.Fatal("distinct IN_LIST branches must never collapse")
	}
	if len(result.FilterBranches) != len(listIDs) {
		t.Fatalf("expected %d branches preserved, got %d", len(listIDs), len(result.FilterBranches))
	}
	var preserved []string
	for _, b := range result.FilterBranches {
		preserved = append(preserved, b.Filters[0].ListID)
	}
	if strings.Join(sortedStrings(preserved), ",") != strings.Join(sortedStrings(listIDs), ",") {
		t.Errorf("preserved listIds = %v, want %v", preserved, listIDs)
	}
}

func TestOptimize_NonORRootUnchanged(t *testing.T) {
	o := New(false)
	fb := model.FilterBranch{
		FilterBranchType: "AND",
		FilterBranches: []model.FilterBranch{
			{
				FilterBranchType: "OR",
				Filters:          []model.Filter{propertyFilter("jobtitle", "CONTAINS", []string{"cloud native"}, false)},
			},
		},
	}
	result := o.Optimize(fb)
	if o.Applied() {
		t.Fatal("expected no optimization for AND-rooted branch")
	}
	if result.FilterBranchType != "AND" || len(result.FilterBranches) != 1 {
		t.Fatalf("expected input unchanged, got %+v", result)
	}
}

func TestOptimize_RealWorldList29996Simulation(t *testing.T) {
	o := New(false)
	titles := []string{
		"cloud native", "kubernetes", "cloud architect", "system administrator",
		"container", "devops", "site reliability", "platform engineer",
		"infrastructure engineer", "cloud engineer", "docker", "devsecops",
		"microservices", "solutions architect",
	}
	var branches []model.FilterBranch
	for _, title := range titles {
		branches = append(branches, andBranch(
			propertyFilter("jobtitle", "CONTAINS", []string{title}, false),
			inListFilter("26716"),
		))
	}
	education := model.FilterBranch{
		FilterBranchType: "AND",
		FilterBranches: []model.FilterBranch{
			{
				FilterBranchType: "UNIFIED_EVENTS",
				Operator:         "HAS_COMPLETED",
				EventTypeID:      "6-58204655",
				Filters: []model.Filter{
					propertyFilter("has_tech_cloud_containers", "IS_ANY_OF", []string{"true"}, false),
				},
			},
		},
	}
	branches = append(branches, education)

	fb := model.FilterBranch{FilterBranchType: "OR", FilterBranches: branches}
	result := o.Optimize(fb)
	if !o.Applied() {
		t.Fatal("expected optimization to apply")
	}
	if len(result.FilterBranches) != 2 {
		t.Fatalf("expected 2 branches (combined job-title + education), got %d", len(result.FilterBranches))
	}

	var jobBranch, eduBranch *model.FilterBranch
	for i := range result.FilterBranches {
		b := &result.FilterBranches[i]
		if len(b.Filters) > 0 && b.Filters[0].Property == "jobtitle" {
			jobBranch = b
		}
		if len(b.FilterBranches) > 0 && b.FilterBranches[0].FilterBranchType == "UNIFIED_EVENTS" {
			eduBranch = b
		}
	}
	if jobBranch == nil {
		t.Fatal("expected combined job-title branch")
	}
	if eduBranch == nil {
		t.Fatal("expected untouched education branch")
	}
	if strings.Join(sortedStrings(jobBranch.Filters[0].Operation.Values), ",") != strings.Join(sortedStrings(titles), ",") {
		t.Errorf("job titles = %v, want %v", jobBranch.Filters[0].Operation.Values, titles)
	}
	if jobBranch.Filters[1].FilterType != "IN_LIST" || jobBranch.Filters[1].ListID != "26716" {
		t.Errorf("expected IN_LIST gate 26716, got %+v", jobBranch.Filters[1])
	}
}

func TestSummary(t *testing.T) {
	o := New(true)
	fb := model.FilterBranch{
		FilterBranchType: "OR",
		FilterBranches: []model.FilterBranch{
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"cloud native"}, false)),
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"kubernetes"}, false)),
		},
	}
	o.Optimize(fb)
	summary := o.Summary()
	if !strings.Contains(summary, "FILTER OPTIMIZER") {
		t.Errorf("summary missing header: %q", summary)
	}
	if !strings.Contains(summary, "Combined") && !strings.Contains(summary, "Optimized") {
		t.Errorf("summary missing optimization detail: %q", summary)
	}
}

func TestOptimize_Deterministic(t *testing.T) {
	fb := model.FilterBranch{
		FilterBranchType: "OR",
		FilterBranches: []model.FilterBranch{
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"cloud native"}, false)),
			andBranch(propertyFilter("jobtitle", "CONTAINS", []string{"kubernetes"}, false)),
		},
	}
	r1 := New(false).Optimize(fb)
	r2 := New(false).Optimize(fb)
	v1 := r1.FilterBranches[0].Filters[0].Operation.Values
	v2 := r2.FilterBranches[0].Filters[0].Operation.Values
	if strings.Join(v1, ",") != strings.Join(v2, ",") {
		t.Errorf("expected deterministic output, got %v vs %v", v1, v2)
	}
}
