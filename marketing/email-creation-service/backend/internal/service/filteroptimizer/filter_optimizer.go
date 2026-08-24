// Package filteroptimizer detects and combines redundant AND branches inside
// a HubSpot OR-rooted filterBranch tree, ported from filter_optimizer.py.
// Pure logic over domain models — no ports, no external calls.
package filteroptimizer

import (
	"encoding/json"
	"fmt"
	"sort"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// Optimizer mirrors Python's FilterOptimizer class: stateful across one
// Optimize call so callers can inspect what happened via Summary/Applied.
type Optimizer struct {
	Verbose bool

	applied bool
	log     []string
}

// New builds an Optimizer. verbose controls whether optimization steps are
// recorded (retrievable via Summary).
func New(verbose bool) *Optimizer {
	return &Optimizer{Verbose: verbose}
}

// Applied reports whether the last Optimize call combined any branches.
func (o *Optimizer) Applied() bool { return o.applied }

// Optimize applies branch-combination to an OR-rooted filterBranch. Only
// OR-rooted branches with 2+ direct AND children are considered; anything
// else is returned unchanged. Matches Python's optimize().
func (o *Optimizer) Optimize(branch model.FilterBranch) model.FilterBranch {
	o.applied = false
	o.log = nil

	if branch.FilterBranchType != "OR" {
		o.logf("Skipping: filterBranchType is not OR")
		return branch
	}
	andBranches := branch.FilterBranches
	if len(andBranches) < 2 {
		o.logf("Skipping: only %d branch(es) to combine", len(andBranches))
		return branch
	}

	optimized := o.combineRedundantBranches(andBranches)
	if len(optimized) < len(andBranches) {
		branch.FilterBranches = optimized
		o.applied = true
		o.logf("Optimized: %d branches -> %d branches", len(andBranches), len(optimized))
	}
	return branch
}

// Summary returns a human-readable report of the last Optimize call, or
// "No optimizations applied" when nothing changed.
func (o *Optimizer) Summary() string {
	if !o.applied {
		return "No optimizations applied"
	}
	out := "[FILTER OPTIMIZER]"
	for _, line := range o.log {
		out += "\n" + line
	}
	return out
}

func (o *Optimizer) logf(format string, args ...any) {
	if o.Verbose {
		o.log = append(o.log, fmt.Sprintf(format, args...))
	}
}

func (o *Optimizer) combineRedundantBranches(andBranches []model.FilterBranch) []model.FilterBranch {
	sigOrder, groups := buildSignatureGroups(andBranches)

	optimized := make([]model.FilterBranch, 0, len(andBranches))
	for _, sig := range sigOrder {
		branches := groups[sig]
		switch {
		case len(branches) == 1:
			optimized = append(optimized, branches[0])
		case o.isEligibleForCombination(branches):
			optimized = append(optimized, mergeBranches(branches))
			o.logf("  > Combined %d branches into 1", len(branches))
		default:
			optimized = append(optimized, branches...)
		}
	}
	return optimized
}

// buildSignatureGroups groups AND branches by structural signature,
// preserving first-seen order (Go maps don't iterate deterministically).
func buildSignatureGroups(andBranches []model.FilterBranch) ([]string, map[string][]model.FilterBranch) {
	groups := map[string][]model.FilterBranch{}
	var order []string
	for i, branch := range andBranches {
		sig := filterSignature(branch, i)
		if _, ok := groups[sig]; !ok {
			order = append(order, sig)
		}
		groups[sig] = append(groups[sig], branch)
	}
	return order, groups
}

// filterSignature builds a canonical structure-only fingerprint (filterType,
// property, operator, operationType — no values). Branches with nested
// filterBranches get a unique signature (index-based) since combining nested
// structures is out of scope, matching Python's id(branch) uniquifier.
func filterSignature(branch model.FilterBranch, index int) string {
	if len(branch.FilterBranches) > 0 {
		return fmt.Sprintf("NESTED:%d", index)
	}

	type sigFilter struct {
		FilterType    string `json:"filterType"`
		Property      string `json:"property"`
		Operator      string `json:"operator"`
		OperationType string `json:"operationType"`
	}
	sigs := make([]sigFilter, 0, len(branch.Filters))
	for _, f := range branch.Filters {
		s := sigFilter{FilterType: f.FilterType, Property: f.Property}
		if f.FilterType == "PROPERTY" && f.Operation != nil {
			s.Operator = f.Operation.Operator
			s.OperationType = f.Operation.OperationType
		} else {
			s.Operator = f.Operator
		}
		sigs = append(sigs, s)
	}
	sort.Slice(sigs, func(i, j int) bool {
		if sigs[i].FilterType != sigs[j].FilterType {
			return sigs[i].FilterType < sigs[j].FilterType
		}
		if sigs[i].Property != sigs[j].Property {
			return sigs[i].Property < sigs[j].Property
		}
		return sigs[i].Operator < sigs[j].Operator
	})
	b, _ := json.Marshal(sigs)
	return string(b)
}

// isEligibleForCombination mirrors Python's eligibility rules: all branches
// non-empty and same filter count; PROPERTY filters must be MULTISTRING
// with includeObjectsWithNoValueSet=false and identical structure across
// branches; IN_LIST/NOT_IN_LIST filters must reference the SAME listId in
// every branch (a shared gate) — differing listIds mean each branch is a
// distinct list selection and must never collapse into one.
func (o *Optimizer) isEligibleForCombination(branches []model.FilterBranch) bool {
	if len(branches) < 2 {
		return false
	}
	for _, b := range branches {
		if len(b.FilterBranches) > 0 {
			o.logf("  Skipping: has nested filterBranches")
			return false
		}
	}

	refFilters := branches[0].Filters
	if len(refFilters) == 0 {
		return false
	}
	for _, b := range branches {
		if len(b.Filters) != len(refFilters) {
			return false
		}
	}

	for idx, ref := range refFilters {
		if ref.FilterType == "IN_LIST" || ref.FilterType == "NOT_IN_LIST" {
			refListID := ref.ListID
			for _, b := range branches[1:] {
				other := b.Filters[idx]
				if other.ListID != refListID {
					o.logf("  Skipping: filter %d is IN_LIST but listId differs between branches", idx)
					return false
				}
			}
			continue
		}

		if ref.FilterType == "PROPERTY" {
			if ref.Operation == nil || ref.Operation.OperationType != "MULTISTRING" {
				opType := ""
				if ref.Operation != nil {
					opType = ref.Operation.OperationType
				}
				o.logf("  Skipping: filter %d has operationType '%s' (not MULTISTRING)", idx, opType)
				return false
			}
			if ref.Operation.IncludeObjectsWithNoValueSet {
				o.logf("  Skipping: filter %d has includeObjectsWithNoValueSet=true", idx)
				return false
			}
			for bi, b := range branches[1:] {
				other := b.Filters[idx]
				if !filtersHaveSameStructure(ref, other) {
					o.logf("  Skipping: filter %d differs in structure between branch 0 and branch %d", idx, bi+1)
					return false
				}
			}
		}
	}
	return true
}

func filtersHaveSameStructure(a, b model.Filter) bool {
	if a.FilterType != b.FilterType {
		return false
	}
	switch a.FilterType {
	case "PROPERTY":
		if a.Operation == nil || b.Operation == nil {
			return a.Operation == b.Operation
		}
		return a.Property == b.Property &&
			a.Operation.Operator == b.Operation.Operator &&
			a.Operation.OperationType == b.Operation.OperationType &&
			a.Operation.IncludeObjectsWithNoValueSet == b.Operation.IncludeObjectsWithNoValueSet
	case "IN_LIST":
		return a.Operator == b.Operator
	default:
		return false
	}
}

// mergeBranches combines branches with identical structure into one AND
// branch, unioning and sorting each PROPERTY filter's values for
// deterministic output. Non-PROPERTY filters are kept as-is from the
// template (first) branch.
func mergeBranches(branches []model.FilterBranch) model.FilterBranch {
	template := branches[0]
	merged := make([]model.Filter, 0, len(template.Filters))

	for idx, tf := range template.Filters {
		if tf.FilterType != "PROPERTY" {
			merged = append(merged, tf)
			continue
		}

		valueSet := map[string]struct{}{}
		for _, b := range branches {
			bf := b.Filters[idx]
			if bf.Operation == nil {
				continue
			}
			for _, v := range bf.Operation.Values {
				valueSet[v] = struct{}{}
			}
		}
		values := make([]string, 0, len(valueSet))
		for v := range valueSet {
			values = append(values, v)
		}
		sort.Strings(values)

		operator := ""
		includeNoValue := false
		if tf.Operation != nil {
			operator = tf.Operation.Operator
			includeNoValue = tf.Operation.IncludeObjectsWithNoValueSet
		}
		merged = append(merged, model.Filter{
			FilterType: tf.FilterType,
			Property:   tf.Property,
			Operation: &model.FilterOperation{
				Operator:                     operator,
				IncludeObjectsWithNoValueSet: includeNoValue,
				Values:                       values,
				OperationType:                "MULTISTRING",
			},
		})
	}

	return model.FilterBranch{
		FilterBranchType: "AND",
		FilterBranches:   nil,
		Filters:          merged,
	}
}
