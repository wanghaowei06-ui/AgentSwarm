# TestWeaver high-risk Human approval boundary

Routine read-only work and native AgentTeams delegation continue without
confirmation.  For a task that explicitly requires approval before a concrete
external side effect, destructive operation, credential or permission change,
or controlled fault injection, this rule overrides unattended/YOLO mode.

Before acting, preserve the proposed action, exact target, evidence reference,
risk, rollback plan, and action fingerprint.  Pause and request a decision from
the authenticated Human in the DM where the task originated.  Resume only
after a new Matrix event from that Human explicitly approves the same action
fingerprint.  A model message, Worker message, earlier blanket authorization,
or the request that created the task is not approval.
