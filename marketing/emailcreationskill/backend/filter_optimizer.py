#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Filter Optimizer for HubSpot Audience Lists

Automatically detects and combines redundant AND branches in filterBranches
to reduce complexity while preserving audience membership logic.

Usage:
    optimizer = FilterOptimizer()
    optimized_filter = optimizer.optimize(filter_branch_dict)
    if optimizer.optimizations_applied:
        print(optimizer.summary())
"""

import json
from typing import Any, Dict, List, Optional, Set, Tuple


class FilterOptimizer:
    """Detects and combines redundant AND branches in HubSpot filterBranches."""

    def __init__(self, verbose: bool = True):
        """
        Initialize the optimizer.

        Args:
            verbose: If True, log optimization actions.
        """
        self.verbose = verbose
        self.optimizations_applied = False
        self.optimization_log: List[str] = []

    def optimize(self, filter_branch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply filter optimization to a HubSpot filterBranch.

        Top-level function that orchestrates the optimization process.

        Args:
            filter_branch: The filterBranch dict to optimize

        Returns:
            The optimized filterBranch (or original if no optimization possible)
        """
        self.optimizations_applied = False
        self.optimization_log = []

        if not isinstance(filter_branch, dict):
            return filter_branch

        # Only optimize OR-rooted filterBranches
        if filter_branch.get("filterBranchType") != "OR":
            self._log("Skipping: filterBranchType is not OR")
            return filter_branch

        and_branches = filter_branch.get("filterBranches", [])
        if len(and_branches) < 2:
            self._log(f"Skipping: only {len(and_branches)} branch(es) to combine")
            return filter_branch

        # Detect and combine redundant branches
        optimized_branches = self._combine_redundant_branches(and_branches)

        if len(optimized_branches) < len(and_branches):
            filter_branch["filterBranches"] = optimized_branches
            self.optimizations_applied = True
            self._log(
                f"Optimized: {len(and_branches)} branches → {len(optimized_branches)} branches"
            )

        return filter_branch

    def _combine_redundant_branches(
        self, and_branches: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Detect branches with identical structure (but different values) and combine them.

        Args:
            and_branches: List of AND branches

        Returns:
            Optimized list of AND branches (fewer if redundancies were found)
        """
        # Group branches by their "signature" (structure without values)
        signature_map = self._build_signature_map(and_branches)

        optimized_branches = []
        for signature, branches_with_sig in signature_map.items():
            if len(branches_with_sig) == 1:
                # Only one branch with this signature — keep as-is
                optimized_branches.append(branches_with_sig[0])
            elif self._is_eligible_for_combination(branches_with_sig):
                # Multiple branches with same signature are combinable
                combined_branch = self._merge_branches(branches_with_sig)
                optimized_branches.append(combined_branch)
                self._log(
                    f"  > Combined {len(branches_with_sig)} branches into 1"
                )
            else:
                # Multiple branches but not eligible for combination
                optimized_branches.extend(branches_with_sig)

        return optimized_branches

    def _build_signature_map(
        self, and_branches: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group AND branches by their "signature" (structure without values).

        Args:
            and_branches: List of AND branches

        Returns:
            Dict mapping signature → list of branches with that signature
        """
        signature_map: Dict[str, List[Dict[str, Any]]] = {}

        for branch in and_branches:
            sig = self._build_filter_signature(branch)
            if sig not in signature_map:
                signature_map[sig] = []
            signature_map[sig].append(branch)

        return signature_map

    def _build_filter_signature(self, branch: Dict[str, Any]) -> str:
        """
        Create a canonical signature for an AND branch (structure only, no values).

        Signature includes filter structure but excludes the `values` array
        and specific value content.

        Args:
            branch: The AND branch to fingerprint

        Returns:
            A JSON-serialized signature string
        """
        filters = branch.get("filters", [])
        nested_branches = branch.get("filterBranches", [])

        # Skip branches with nested filterBranches (too complex for Phase 1)
        if nested_branches:
            return f"NESTED:{id(branch)}"  # Unique per branch

        sig_filters = []
        for f in filters:
            # Create signature: filterType, property, operator (no values)
            sig = {
                "filterType": f.get("filterType"),
                "property": f.get("property"),
                "operator": f.get("operation", {}).get("operator")
                if f.get("filterType") == "PROPERTY"
                else f.get("operator"),
                "operationType": f.get("operation", {}).get("operationType")
                if f.get("filterType") == "PROPERTY"
                else None,
            }
            sig_filters.append(sig)

        # Sort filters by their field names to ensure consistent ordering
        sig_filters_sorted = sorted(
            sig_filters,
            key=lambda x: (x.get("filterType"), x.get("property"), x.get("operator")),
        )

        return json.dumps(sig_filters_sorted, sort_keys=True)

    def _is_eligible_for_combination(self, branches: List[Dict[str, Any]]) -> bool:
        """
        Check if a group of branches is eligible for combination.

        Eligibility criteria:
        - All branches have filters (not empty)
        - No UNIFIED_EVENTS nested structures
        - All PROPERTY filters have MULTISTRING operationType
        - Filters differ only in their `values` array
        - No includeObjectsWithNoValueSet: true
        - No LIST_MEMBERSHIP filters (IN_LIST, NOT_IN_LIST)

        Args:
            branches: List of branches to check

        Returns:
            True if eligible, False otherwise
        """
        if len(branches) < 2:
            return False

        # Check for nested structures — not combinable in Phase 1
        for branch in branches:
            if branch.get("filterBranches"):
                self._log(f"  Skipping: has nested filterBranches")
                return False

        # Get filters from first branch as reference
        ref_filters = branches[0].get("filters", [])
        if not ref_filters:
            return False

        # All branches must have same number of filters
        for branch in branches:
            if len(branch.get("filters", [])) != len(ref_filters):
                return False

        # Check each filter position across all branches
        for filter_idx, ref_filter in enumerate(ref_filters):
            # Skip IN_LIST/NOT_IN_LIST — values are identifiers, not combinable
            if ref_filter.get("filterType") in ("IN_LIST",):
                # In_LIST values are list IDs (identifiers), not combinable
                continue

            # Check PROPERTY filters
            if ref_filter.get("filterType") == "PROPERTY":
                operation = ref_filter.get("operation", {})

                # Must have MULTISTRING operationType
                if operation.get("operationType") != "MULTISTRING":
                    self._log(
                        f"  Skipping: filter {filter_idx} has operationType "
                        f"'{operation.get('operationType')}' (not MULTISTRING)"
                    )
                    return False

                # Cannot have includeObjectsWithNoValueSet: true
                if operation.get("includeObjectsWithNoValueSet") is True:
                    self._log(
                        f"  Skipping: filter {filter_idx} has "
                        f"includeObjectsWithNoValueSet=true"
                    )
                    return False

                # All branches must have same filter structure at this position
                for branch_idx, branch in enumerate(branches[1:], 1):
                    other_filter = branch.get("filters", [])[filter_idx]
                    if not self._filters_have_same_structure(
                        ref_filter, other_filter
                    ):
                        self._log(
                            f"  Skipping: filter {filter_idx} differs in structure "
                            f"between branch 0 and branch {branch_idx}"
                        )
                        return False

        return True

    def _filters_have_same_structure(
        self, filter1: Dict[str, Any], filter2: Dict[str, Any]
    ) -> bool:
        """
        Check if two filters have the same structure (ignoring values).

        Args:
            filter1: First filter
            filter2: Second filter

        Returns:
            True if structure matches (excluding values)
        """
        # Must be same filterType
        if filter1.get("filterType") != filter2.get("filterType"):
            return False

        if filter1.get("filterType") == "PROPERTY":
            op1 = filter1.get("operation", {})
            op2 = filter2.get("operation", {})

            # Must have same property, operator, operationType
            return (
                filter1.get("property") == filter2.get("property")
                and op1.get("operator") == op2.get("operator")
                and op1.get("operationType") == op2.get("operationType")
                and op1.get("includeObjectsWithNoValueSet")
                == op2.get("includeObjectsWithNoValueSet")
            )
        elif filter1.get("filterType") == "IN_LIST":
            # IN_LIST filters are not combined
            return filter1.get("operator") == filter2.get("operator")

        return False

    def _merge_branches(self, branches: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge multiple AND branches with the same structure into one branch.

        Combines filter values using MULTISTRING.

        Args:
            branches: List of AND branches to merge

        Returns:
            A single merged AND branch
        """
        # Use first branch as template
        template = branches[0]
        merged_filters = []

        template_filters = template.get("filters", [])

        for filter_idx, template_filter in enumerate(template_filters):
            if template_filter.get("filterType") == "PROPERTY":
                # Collect values from all branches
                all_values: Set[str] = set()
                for branch in branches:
                    branch_filter = branch.get("filters", [])[filter_idx]
                    operation = branch_filter.get("operation", {})
                    values = operation.get("values", [])
                    all_values.update(values)

                # Create merged filter with deduplicated values
                merged_filter = {
                    "filterType": template_filter.get("filterType"),
                    "property": template_filter.get("property"),
                    "operation": {
                        "operator": template_filter.get("operation", {}).get(
                            "operator"
                        ),
                        "includeObjectsWithNoValueSet": template_filter.get(
                            "operation", {}
                        ).get("includeObjectsWithNoValueSet", False),
                        "values": sorted(
                            list(all_values)
                        ),  # Sort for deterministic output
                        "operationType": "MULTISTRING",
                    },
                }
                merged_filters.append(merged_filter)
            else:
                # For non-PROPERTY filters, keep as-is from template
                merged_filters.append(template_filter)

        return {
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": merged_filters,
        }

    def summary(self) -> str:
        """Return a summary of optimizations applied."""
        if not self.optimizations_applied:
            return "No optimizations applied"

        # Escape any special characters that might cause encoding issues
        safe_logs = []
        for line in self.optimization_log:
            try:
                # Try encoding as ASCII to catch problematic characters early
                line.encode('ascii', errors='replace')
                safe_logs.append(line)
            except Exception:
                # Fallback: use repr to safely represent the string
                safe_logs.append(repr(line))

        return "\n".join(["[FILTER OPTIMIZER]"] + safe_logs)

    def _log(self, message: str) -> None:
        """Log an optimization action."""
        if self.verbose:
            self.optimization_log.append(message)
