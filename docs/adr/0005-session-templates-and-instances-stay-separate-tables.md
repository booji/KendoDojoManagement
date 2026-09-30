# Session Templates and Sessions stay separate tables

**Session Templates** (the recurring rule) and **Sessions** (one dated event) are stored as
two parallel sets of three tables — `session_template{,_segments,_segment_types}`
and `session_instance{,_segments,_segment_types}` — with near-identical columns.
We keep all six rather than collapsing them into three tables with a
discriminator column.

The resemblance is shallower than it looks, and the two have already diverged:
a Session carries `cancelled` and the check-in window overrides, a template
carries its recurrence rule (`recurrence`, `day_of_week`, `recurrence_days`,
`interval_weeks`, `start_date`, `end_date`). One
merged table would have to make every one of those columns nullable and trust
application code to know which apply to which kind of row. The segment tables
would then need a polymorphic parent — a column that points at either a
template or a Session — which a foreign key cannot constrain. Six tables that
each say exactly what they hold are worth more than three that need a
discriminator to be read correctly.

Decided in the schema review, issue #418.
