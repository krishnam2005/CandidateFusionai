"""
normalizers.skill_normalizer — Skill alias resolution and canonical naming.

Uses a curated alias dictionary plus RapidFuzz for fuzzy matching to map
raw skill strings to canonical forms.

Why RapidFuzz over FuzzyWuzzy / difflib?
  - 10-100x faster due to C++ implementation.
  - Actively maintained with Python 3.12 support.
  - Supports token_sort_ratio for word-order-insensitive matching.
  - MIT licensed.

The canonical skill dictionary is data-driven — adding a new alias requires
only editing ``SKILL_ALIASES``, not code changes.  This aligns with the
Open/Closed Principle.
"""

from __future__ import annotations

from rapidfuzz import fuzz, process

from utils.logging import get_logger

log = get_logger(__name__)

# ── Canonical skill alias map ─────────────────────────────────────────────────
# Keys are canonical names; values are lists of known aliases.
# This dictionary would be externalized to a database in a full production system.
SKILL_ALIASES: dict[str, list[str]] = {
    # Programming Languages
    "Python": ["python3", "python 3", "py", "python2", "python 2.7"],
    "JavaScript": ["js", "javascript", "java script", "ecmascript", "es6", "es2015", "es2016", "es2017"],
    "TypeScript": ["ts", "typescript"],
    "Java": ["java8", "java 8", "java11", "java 11", "java17", "java 17"],
    "C++": ["cpp", "c plus plus", "c++11", "c++14", "c++17", "c++20"],
    "C#": ["csharp", "c sharp", ".net c#"],
    "Go": ["golang", "go lang"],
    "Rust": ["rust lang", "rust-lang"],
    "Ruby": ["ruby on rails", "ror"],
    "Swift": ["swift ui", "swiftui"],
    "Kotlin": ["kotlin android"],
    "PHP": ["php7", "php8", "php 7", "php 8"],
    "Scala": ["scala lang"],
    "R": ["r language", "r programming", "r stats"],
    "MATLAB": ["matlab r2020", "matlab r2021"],
    "Shell": ["bash", "shell scripting", "bash scripting", "zsh", "sh"],
    "SQL": ["sql query", "structured query language"],
    # Web Frameworks
    "React": ["reactjs", "react.js", "react js", "react native"],
    "Vue.js": ["vuejs", "vue", "vue js", "vue 3", "vue2"],
    "Angular": ["angularjs", "angular js", "angular2", "angular 2", "angular 12", "angular 14"],
    "Next.js": ["nextjs", "next js"],
    "Nuxt.js": ["nuxtjs", "nuxt js"],
    "Django": ["django rest framework", "drf", "django framework"],
    "Flask": ["flask python", "flask api"],
    "FastAPI": ["fast api", "fastapi python"],
    "Spring Boot": ["springboot", "spring framework", "spring mvc"],
    "Express.js": ["expressjs", "express js", "express"],
    "Node.js": ["nodejs", "node js", "node"],
    "Svelte": ["svelte js", "sveltekit"],
    # Databases
    "PostgreSQL": ["postgres", "postgresql", "postgresdb", "psql"],
    "MySQL": ["mysql db", "mysql database"],
    "MongoDB": ["mongo", "mongodb", "mongo db"],
    "Redis": ["redis cache", "redis db"],
    "Elasticsearch": ["elastic search", "es", "elk"],
    "Cassandra": ["apache cassandra", "cassandra db"],
    "DynamoDB": ["dynamodb", "dynamo db", "aws dynamodb"],
    "SQLite": ["sqlite3", "sqlite 3"],
    "Oracle": ["oracle db", "oracle database", "oracle sql"],
    # Cloud & DevOps
    "AWS": ["amazon web services", "amazon aws", "aws cloud"],
    "GCP": ["google cloud", "google cloud platform", "google gcp"],
    "Azure": ["microsoft azure", "azure cloud", "ms azure"],
    "Docker": ["docker container", "docker containers", "containerization"],
    "Kubernetes": ["k8s", "kube", "kubernetes orchestration"],
    "Terraform": ["terraform iac", "hashicorp terraform"],
    "Ansible": ["ansible automation", "ansible playbook"],
    "Jenkins": ["jenkins ci", "jenkins ci/cd"],
    "GitHub Actions": ["github actions ci", "gh actions"],
    "GitLab CI": ["gitlab ci/cd", "gitlab pipeline"],
    # Machine Learning / AI
    "TensorFlow": ["tensorflow 2", "tf", "tensorflow2"],
    "PyTorch": ["pytorch", "torch"],
    "scikit-learn": ["sklearn", "scikit learn"],
    "Keras": ["keras api", "tf.keras"],
    "Pandas": ["pandas python", "pandas df"],
    "NumPy": ["numpy", "np"],
    "OpenCV": ["cv2", "open cv"],
    "Hugging Face": ["huggingface", "hf transformers", "hugging face transformers"],
    "LangChain": ["lang chain"],
    "Apache Spark": ["spark", "pyspark", "spark ml"],
    # Tools & Practices
    "Git": ["git version control", "git scm"],
    "REST API": ["rest", "restful", "restful api", "rest apis", "restful apis"],
    "GraphQL": ["graph ql", "graphql api"],
    "gRPC": ["grpc", "grpc api"],
    "Microservices": ["micro services", "microservice architecture"],
    "CI/CD": ["cicd", "continuous integration", "continuous deployment", "continuous delivery"],
    "Agile": ["agile methodology", "agile scrum", "scrum"],
    "Scrum": ["scrum methodology", "scrum framework"],
    "TDD": ["test driven development", "test-driven development"],
    "DevOps": ["dev ops", "devops practices"],
    # Data Engineering
    "Apache Kafka": ["kafka", "confluent kafka"],
    "Apache Airflow": ["airflow", "airflow dag"],
    "dbt": ["data build tool", "dbt cloud", "dbt core"],
    "Snowflake": ["snowflake db", "snowflake data warehouse"],
    "BigQuery": ["google bigquery", "bq"],
    "Databricks": ["databricks spark", "databricks platform"],
}

# Reverse map: alias (lowercase) → canonical name
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in SKILL_ALIASES.items():
    _ALIAS_TO_CANONICAL[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[_alias.lower()] = _canonical

# All canonical names (for fuzzy matching fallback)
_ALL_CANONICAL_LOWER: list[str] = [k.lower() for k in SKILL_ALIASES]

# Fuzzy match threshold — strings below this score are not considered matches
_FUZZY_THRESHOLD = 85


class SkillNormalizer:
    """
    Normalizes raw skill strings to their canonical forms.

    Resolution strategy (in order):
      1. Exact match (case-insensitive) against the alias → canonical map.
      2. Fuzzy match against the alias map with RapidFuzz (threshold 85).
      3. Return the title-cased original if no match is found.
    """

    @staticmethod
    def normalize(raw: str | None) -> str:
        """
        Normalize a single skill string.

        Never returns None — if no canonical form is found, returns the
        title-cased raw string so that unknown skills are still captured.
        """
        if not raw:
            return ""

        stripped = raw.strip()
        lower = stripped.lower()

        # ── 1. Exact alias lookup ────────────────────────────────────────────
        if lower in _ALIAS_TO_CANONICAL:
            return _ALIAS_TO_CANONICAL[lower]

        # ── 2. Fuzzy match against all known aliases ─────────────────────────
        best_match = process.extractOne(
            lower,
            _ALIAS_TO_CANONICAL.keys(),
            scorer=fuzz.token_sort_ratio,
            score_cutoff=_FUZZY_THRESHOLD,
        )
        if best_match is not None:
            matched_alias, score, _ = best_match
            canonical = _ALIAS_TO_CANONICAL[matched_alias]
            log.debug(
                "skill_fuzzy_matched",
                raw=stripped,
                matched_alias=matched_alias,
                canonical=canonical,
                score=score,
            )
            return canonical

        # ── 3. Unknown skill — preserve with title casing ────────────────────
        return stripped.title()

    @staticmethod
    def normalize_list(raw_skills: list[str]) -> list[str]:
        """
        Normalize a list of skill strings, removing empty results and duplicates.

        Order is preserved; later duplicates are dropped.
        """
        seen: set[str] = set()
        result: list[str] = []
        for raw in raw_skills:
            canonical = SkillNormalizer.normalize(raw)
            if canonical and canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
        return result

    @staticmethod
    def get_aliases(canonical: str) -> list[str]:
        """Return all known aliases for a canonical skill name."""
        return SKILL_ALIASES.get(canonical, [])
