# Database Schema

```mermaid
erDiagram
    users {
        string id PK
        string email UK
        string hashed_password
        string role
        bool is_active
        string theme
        string pending_challenge
        timestamptz challenge_issued_at
        timestamptz locked_until
        int login_failures
    }
    passkey_credentials {
        string id PK
        string user_id FK
        bytes credential_id UK
        bytes public_key
        int sign_count
        string label
        string aaguid
        timestamptz created_at
        timestamptz last_used_at
    }
    recovery_codes {
        string id PK
        string user_id FK
        string code_hash
        string set_id
        timestamptz used_at
        timestamptz created_at
    }
    recovery_attempts {
        string id PK
        string user_id FK
        timestamptz attempted_at
        string ip_address
        bool success
    }
    admin_recovery_tokens {
        string id PK
        string user_id FK
        string created_by_id FK
        string token_hash
        timestamptz expires_at
        timestamptz used_at
        timestamptz created_at
    }
    members {
        string id PK
        string email UK
        string full_name
        string dob
        string join_date
        string membership_status
        bool is_coach
        bool is_first_aider
        string emergency_contact_name
        string emergency_contact_phone
        string federation_number
        bool parental_consent_obtained
        string user_id
    }
    session_types {
        string id PK
        string name UK
        string colour
    }
    session_templates {
        string id PK
        string session_type_id FK
        string title
        string start_date
        string start_time
        int duration_minutes
        string recurrence
        int day_of_week
        string location
        text recurrence_days
        int interval_weeks
        text info
        text coach_notes
        bool is_active
    }
    session_instances {
        string id PK
        string session_type_id FK
        string template_id FK
        string date
        string start_time
        int duration_minutes
        string notes
        bool cancelled
        string location
        text info
        text coach_notes
        string checkin_url
    }
    attendance {
        string id PK
        string session_id
        string member_id
        string visitor_name
        string checked_in_at
        string recorded_by
    }
    checkin_tokens {
        string id PK
        string token UK
        string token_lookup UK
        string session_id
        string expires_at
        timestamptz used_at
    }
    grade_history {
        string id PK
        string member_id
        string grade
        string display_name
        string promoted_at
        string awarded_by
    }
    dojo_settings {
        string id PK
        string dojo_name
        string logo_url
        string primary_colour
        timestamptz updated_at
    }

    users ||--o{ passkey_credentials : "has"
    users ||--o{ recovery_codes : "has"
    users ||--o{ recovery_attempts : "has"
    users ||--o{ admin_recovery_tokens : "issued to"
    users ||--o{ admin_recovery_tokens : "created by"
    session_types ||--o{ session_templates : "defines"
    session_types ||--o{ session_instances : "typed as"
    session_templates ||--o{ session_instances : "generates"
```

## Notes

- `attendance`, `checkin_tokens`, `grade_history` — `session_id`, `member_id`, `recorded_by` are bare strings with no FK constraints enforced at DB level.
- `members.user_id` — links a member to a user account but also unconstrained at DB level.
