# Requirements Document

## Introduction

The SHCE Package Verification and Self-Healing Engine is a safety subsystem for PC Doctor's Self-Healing Core Engine (SHCE). Its purpose is to prevent the generation of invalid or unverifiable installation commands before they are presented to the user or executed. When a user requests installation of a package (e.g., "Install Binance"), the system must verify package existence through a prioritised chain of local and network sources before generating any `apt install` or equivalent command. If verification fails, SHCE must refuse command generation, explain why, and optionally offer alternatives. When a previously executed installation command fails at runtime (e.g., "E: Unable to locate package"), the self-healing logic captures the error, queries all available knowledge sources, and generates corrected alternatives.

## Glossary

- **SHCE**: Self-Healing Core Engine — the intelligent repair and command mutation subsystem of PC Doctor.
- **Package_Verifier**: The new subsystem responsible for verifying package existence before command generation.
- **Package_Knowledge_Store**: A SQLite table (`package_knowledge`) that records known packages, their install methods, verification status, and fallback approaches.
- **Verification_Pipeline**: The ordered chain of verification sources: Local Cache → apt-cache → Package Knowledge Store → Local RAG → Web RAG.
- **Confidence_Score**: An integer (0–100) representing how certain the system is that a package is real and installable.
- **Verification_Status**: One of `VERIFIED`, `UNVERIFIED`, or `UNKNOWN`, assigned after running the Verification_Pipeline.
- **Intent_Detector**: The component that identifies whether a user query is a package installation request.
- **Command_Generator**: The component within SHCE that produces shell installation commands.
- **Self_Healing_Loop**: The post-execution error capture and correction pipeline triggered when an installed command fails.
- **Local_RAG**: The local vector knowledge base (`knowledge.db`) already present in the backend.
- **Web_RAG**: An internet-based knowledge query used only when the system is online.
- **apt-cache**: The local APT package metadata tool available on Debian/Ubuntu systems.
- **Fuzzy_Match**: A similarity-based package name lookup that finds packages with names similar to the requested one.

---

## Requirements

### Requirement 1: Intent Detection for Installation Requests

**User Story:** As a user, I want PC Doctor to detect when I am asking it to install a package, so that the verification pipeline is triggered before any command is generated.

#### Acceptance Criteria

1. WHEN a user query contains phrases such as "install", "get", "add", or "setup" followed by a package name, THE Intent_Detector SHALL classify the query as an installation request.
2. WHEN the Intent_Detector classifies a query as an installation request, THE SHCE SHALL extract the target package name from the query before proceeding.
3. IF the Intent_Detector cannot extract a package name from the query, THEN THE SHCE SHALL return a clarification prompt rather than generate any installation command.
4. THE Intent_Detector SHALL treat package name extraction as case-insensitive and SHALL normalise the extracted name to lowercase before passing it to the Verification_Pipeline.

---

### Requirement 2: Package Verification Pipeline

**User Story:** As a developer, I want SHCE to verify every package name through an ordered chain of sources, so that only packages confirmed to exist are used in generated commands.

#### Acceptance Criteria

1. WHEN an installation request is received, THE Package_Verifier SHALL execute verification sources in priority order: (1) apt-cache search, (2) apt-cache show, (3) Package_Knowledge_Store, (4) Local_RAG, (5) Web_RAG.
2. WHEN `apt-cache show <package_name>` returns a result with no error, THE Package_Verifier SHALL set Verification_Status to `VERIFIED` and Confidence_Score to 100.
3. WHEN `apt-cache search <package_name>` returns at least one matching result, THE Package_Verifier SHALL set Verification_Status to `VERIFIED` and Confidence_Score to at least 80.
4. WHEN the Package_Knowledge_Store contains a record for the requested package with `verification_status = 'verified'`, THE Package_Verifier SHALL set Verification_Status to `VERIFIED` and Confidence_Score to 80.
5. WHEN Local_RAG returns a matching result for the package name, THE Package_Verifier SHALL set Verification_Status to `VERIFIED` and Confidence_Score to 60.
6. WHEN Web_RAG returns a matching result and the system is online, THE Package_Verifier SHALL set Verification_Status to `VERIFIED` and Confidence_Score to 60.
7. WHILE the system is offline, THE Package_Verifier SHALL skip Web_RAG and proceed with the result from the previous verification steps.
8. WHEN no verification source confirms the package, THE Package_Verifier SHALL set Verification_Status to `UNVERIFIED` and Confidence_Score to 0.
9. WHEN a Fuzzy_Match is found (package name similarity above 70%), THE Package_Verifier SHALL set Confidence_Score to 40 and include the closest match name in the verification result.
10. THE Package_Verifier SHALL return a structured verification result containing: `package`, `verified` (boolean), `confidence` (integer 0–100), `source` (string), and either `command` (string) or `reason` (string).

---

### Requirement 3: Command Generation Gate

**User Story:** As a user, I want SHCE to only generate installation commands for packages it can verify, so that I am never given a command that will fail due to an unknown package.

#### Acceptance Criteria

1. WHEN Confidence_Score is 70 or above, THE Command_Generator SHALL generate the installation command and include it in the response.
2. WHEN Confidence_Score is below 70, THE Command_Generator SHALL NOT generate any installation command.
3. WHEN Confidence_Score is below 70, THE SHCE SHALL return the message: "Package could not be verified locally. No installation command generated." along with the Confidence_Score and Verification_Status.
4. WHEN Confidence_Score is between 40 and 69, THE SHCE SHALL include the closest Fuzzy_Match package name and its suggested command as an alternative in the response.
5. THE Command_Generator SHALL use the install method recorded in the Package_Knowledge_Store (e.g., `apt`, `snap`, `external_repo`) when available, rather than defaulting to `apt install`.
6. WHEN Confidence_Score is between 40 and 69 and a command is included as an alternative suggestion, THE SHCE SHALL label the command as unconfirmed and require explicit user confirmation before it is executed.

---

### Requirement 4: Package Knowledge Store

**User Story:** As a developer, I want a local SQLite table that records known packages with their verification metadata, so that the system can verify packages without internet access.

#### Acceptance Criteria

1. THE Package_Knowledge_Store SHALL exist as a table named `package_knowledge` in the existing `knowledge.db` SQLite database.
2. THE Package_Knowledge_Store table SHALL contain columns: `id` (integer primary key), `package_name` (text unique), `install_method` (text), `repository_required` (text), `verification_status` (text), `last_verified` (text), `fallback_methods` (text).
3. WHEN the SHCE backend starts, THE Package_Knowledge_Store SHALL be initialised with a seed set of at least 20 commonly used packages, including `git`, `docker`, `nodejs`, `python3`, `curl`, `wget`, `vim`, `htop`, `tmux`, `build-essential`, `net-tools`, `ffmpeg`, `vlc`, `gimp`, `libreoffice`, `openssh-server`, `ufw`, `fail2ban`, `nginx`, and `postgresql`.
4. WHEN a package is successfully verified via apt-cache and is not already present in the Package_Knowledge_Store, THE Package_Knowledge_Store SHALL insert a new record for that package with `verification_status = 'verified'` and the current timestamp in `last_verified`.
5. WHEN a package fails all verification steps, THE Package_Knowledge_Store SHALL insert or update a record for that package with `verification_status = 'unknown'`.
6. THE Package_Knowledge_Store SHALL support querying by `package_name` with exact match and by normalised lowercase comparison.

---

### Requirement 5: Self-Healing on Installation Failure

**User Story:** As a user, I want SHCE to automatically recover when an installation command fails at runtime, so that I receive corrected alternatives without manual diagnosis.

#### Acceptance Criteria

1. WHEN a terminal error matching the pattern `unable to locate package <name>` is captured, THE Self_Healing_Loop SHALL classify the error as an `installation_failure` and extract the package name.
2. WHEN an `installation_failure` error is detected, THE Self_Healing_Loop SHALL query the Package_Knowledge_Store and Local_RAG for alternative install methods for the failed package name.
3. WHEN alternative install methods are found (e.g., `docker.io` instead of `docker`, or adding an external repository), THE Self_Healing_Loop SHALL generate corrected command candidates and rank them by Confidence_Score.
4. WHEN no alternative install method is found and the system is online, THE Self_Healing_Loop SHALL query Web_RAG and append any discovered alternatives to the candidate list.
5. WHEN corrected command candidates are available, THE SHCE SHALL enqueue the highest-ranked candidate in the `shce_queue` table and present it to the user for approval.
6. WHEN the Package_Knowledge_Store contains a `repository_required` value for the failed package, THE Self_Healing_Loop SHALL generate a two-step candidate: first add the repository, then install the package.
7. IF no corrected candidates can be generated after exhausting all sources, THEN THE Self_Healing_Loop SHALL return a message stating the package cannot be installed through any verified method, and SHALL update the Package_Knowledge_Store record to `verification_status = 'unknown'`.

---

### Requirement 6: Confidence Scoring Model

**User Story:** As a developer, I want a defined confidence scoring model, so that the system has consistent, predictable thresholds for command generation and user confirmation.

#### Acceptance Criteria

1. THE Package_Verifier SHALL assign Confidence_Score 100 when `apt-cache show` returns an exact match for the package name.
2. THE Package_Verifier SHALL assign Confidence_Score 80 when the Package_Knowledge_Store contains a verified record for the package name.
3. THE Package_Verifier SHALL assign Confidence_Score 60 when the package is confirmed only through Local_RAG or Web_RAG.
4. THE Package_Verifier SHALL assign Confidence_Score 40 when only a Fuzzy_Match is found (no exact verification).
5. THE Package_Verifier SHALL assign Confidence_Score 20 when the package name is recognised but cannot be confirmed through any source.
6. THE Package_Verifier SHALL assign Confidence_Score 0 when the package is completely unknown across all sources.
7. WHEN Confidence_Score is below 70, THE Command_Generator SHALL NOT execute or enqueue any installation command without explicit user confirmation.
8. THE Package_Verifier SHALL expose the Confidence_Score in its API response for every verification request.

---

### Requirement 7: Verification Response Format

**User Story:** As a developer integrating with the SHCE API, I want a consistent JSON response format for package verification results, so that the frontend and other consumers can reliably parse and display verification outcomes.

#### Acceptance Criteria

1. WHEN a package is verified with Confidence_Score of 70 or above, THE SHCE SHALL return a JSON response containing: `package` (string), `verified` (boolean true), `confidence` (integer), `source` (string), `command` (string).
2. WHEN a package cannot be verified, THE SHCE SHALL return a JSON response containing: `package` (string), `verified` (boolean false), `confidence` (integer), `reason` (string), `command` (null).
3. WHEN a Fuzzy_Match is found but no exact verification exists, THE SHCE SHALL include a `suggestion` field in the response containing the closest match package name and its suggested command.
4. THE SHCE SHALL include a `verification_source` field in every response, set to one of: `apt-cache`, `package_knowledge_store`, `local_rag`, `web_rag`, `fuzzy_match`, or `none`.
5. THE Package_Verifier SHALL produce responses where `parse(format(response)) == response` for all valid verification result objects (round-trip serialisation property).

---

### Requirement 8: Offline Safety Guarantee

**User Story:** As a user running PC Doctor without internet access, I want SHCE to never generate installation commands for unverified packages even when offline, so that offline repairs do not introduce broken commands.

#### Acceptance Criteria

1. WHILE the system is offline, THE Package_Verifier SHALL complete verification using only apt-cache and the Package_Knowledge_Store.
2. WHILE the system is offline, THE SHCE SHALL NOT attempt Web_RAG queries that would time out or fail silently.
3. WHEN the system is offline and a package cannot be verified locally, THE SHCE SHALL respond with: "Package could not be verified locally. Internet access unavailable. No installation command generated."
4. WHEN the system is offline and the Package_Knowledge_Store contains a record with `install_method = 'external_repo'`, THE SHCE SHALL inform the user that the package requires an external repository that cannot be added while offline.
5. THE Package_Verifier SHALL complete the full offline verification pipeline within 5 seconds for any single package query.

---

### Requirement 9: API Endpoints for Package Verification

**User Story:** As a developer, I want dedicated API endpoints for package verification so that the frontend and other backend modules can trigger verification and retrieve results independently of command mutation.

#### Acceptance Criteria

1. THE SHCE SHALL expose a `POST /api/shce/verify-package` endpoint that accepts a JSON body with `package_name` (string) and returns the verification result in the standard response format.
2. THE SHCE SHALL expose a `GET /api/shce/package-knowledge` endpoint that returns the full contents of the Package_Knowledge_Store as a paginated list.
3. THE SHCE SHALL expose a `POST /api/shce/package-knowledge` endpoint that accepts a JSON body to manually add or update a package record in the Package_Knowledge_Store.
4. WHEN the `POST /api/shce/verify-package` endpoint receives a request with a missing or empty `package_name`, THE SHCE SHALL return HTTP 400 with a descriptive error message.
5. WHEN the `POST /api/shce/verify-package` endpoint is called, THE SHCE SHALL run the full Verification_Pipeline and return results within 10 seconds.
