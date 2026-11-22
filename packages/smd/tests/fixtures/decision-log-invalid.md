---
schema: decision-log@1
---

# Backend decisions

## Use PostgreSQL
status: accepted
date: 2026-11-10
tags: database, backend
owner: jane.doe

### Context
We need relational integrity and JSON support.

### Decision
PostgreSQL 17, managed.

## Use Redis for caching
status: maybe
date: 10/11/2026

### Context
Read-heavy endpoints.
