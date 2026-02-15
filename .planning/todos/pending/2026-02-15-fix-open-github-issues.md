---
created: 2026-02-15T14:29:04.193Z
title: Fix open GitHub issues
area: general
files: []
---

## Problem

7 open GitHub issues remain from the code review campaign. These are minor code quality findings across all modules plus one important singleton issue:

- #32 Common: Module-level singletons make testing and reconfiguration difficult (important)
- #36 Ingestion: Minor code quality findings
- #37 Agent: Minor code quality findings
- #38 Retrieval: Minor code quality findings
- #39 Common: Minor code quality findings
- #40 Frontend + Eval: Minor code quality findings
- #43 API: Minor code quality findings

## Solution

Work through each issue, apply fixes, run tests, and close issues via `gh issue close`. Consider batching related fixes into logical commits. The minor issues (#36-40, #43) are enhancement-level; #32 (singletons) is the most impactful.
