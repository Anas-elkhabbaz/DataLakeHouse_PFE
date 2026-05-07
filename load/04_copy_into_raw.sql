-- =============================================================================
-- COPY INTO : charge les 4 CSV depuis le stage vers les tables brutes RAW.*
-- Positions $N vérifiées avec inspect_headers.py sur le dataset réel (mai 2026)
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA RAW;
USE WAREHOUSE PFE_WH;

-- ---------------------------------------------------------------------------
-- TABLE : RAW.ISSUES — 37 colonnes dans le CSV
-- Positions vérifiées :
--   $1=id  $2=key  $3=summary  $37=description  $35=created
--   $33=resolutiondate  $25=issuetype.name  $6=resolution.name
--   $5=resolution.description  $8=priority.name  $13=status.name
--   $28=project.key  $10=assignee  $21=reporter  $19=creator
--   $22=votes.votes  $34=watches.watchCount
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE RAW.ISSUES (
    id                      VARCHAR,
    key                     VARCHAR,
    summary                 VARCHAR,
    description             VARCHAR,
    created                 VARCHAR,
    resolutiondate          VARCHAR,
    issuetype_name          VARCHAR,
    resolution_name         VARCHAR,
    resolution_description  VARCHAR,
    priority_name           VARCHAR,
    status_name             VARCHAR,
    project_key             VARCHAR,
    assignee                VARCHAR,
    reporter                VARCHAR,
    creator                 VARCHAR,
    votes_votes             VARCHAR,
    watches_watchcount      VARCHAR
)
COMMENT = 'Bronze : toutes les issues JIRA (filtre SPARK appliqué en staging)';

COPY INTO RAW.ISSUES (
    id, key, summary, description, created, resolutiondate,
    issuetype_name, resolution_name, resolution_description,
    priority_name, status_name, project_key,
    assignee, reporter, creator, votes_votes, watches_watchcount
)
FROM (
    SELECT
        $1,   -- id
        $2,   -- key
        $3,   -- summary
        $37,  -- description
        $35,  -- created
        $33,  -- resolutiondate
        $25,  -- issuetype.name
        $6,   -- resolution.name
        $5,   -- resolution.description
        $8,   -- priority.name
        $13,  -- status.name
        $28,  -- project.key
        $10,  -- assignee
        $21,  -- reporter
        $19,  -- creator
        $22,  -- votes.votes
        $34   -- watches.watchCount
    FROM @RAW.CSV_STAGE/issues.csv.gz
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.CSV_STAGE')
ON_ERROR = 'CONTINUE';

-- ---------------------------------------------------------------------------
-- TABLE : RAW.COMMENTS — 6 colonnes ($1-$6, positions exactes)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE RAW.COMMENTS (
    key             VARCHAR,
    comment_id      VARCHAR,
    comment_author  VARCHAR,
    comment_body    VARCHAR,
    comment_created VARCHAR,
    comment_updated VARCHAR
)
COMMENT = 'Bronze : commentaires JIRA bruts';

COPY INTO RAW.COMMENTS (key, comment_id, comment_author, comment_body, comment_created, comment_updated)
FROM (SELECT $1, $2, $3, $4, $5, $6 FROM @RAW.CSV_STAGE/comments.csv.gz)
FILE_FORMAT = (FORMAT_NAME = 'RAW.CSV_STAGE')
ON_ERROR = 'CONTINUE';

-- ---------------------------------------------------------------------------
-- TABLE : RAW.CHANGELOG — 11 colonnes
-- Positions vérifiées : $2=key  $4=author  $5=created  $6=field
--                       $9=fromString  $11=toString
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE RAW.CHANGELOG (
    key         VARCHAR,
    author      VARCHAR,
    created     VARCHAR,
    field       VARCHAR,
    fromstring  VARCHAR,
    tostring    VARCHAR
)
COMMENT = 'Bronze : historique des changements JIRA';

COPY INTO RAW.CHANGELOG (key, author, created, field, fromstring, tostring)
FROM (
    SELECT
        $2,   -- key
        $4,   -- author
        $5,   -- created
        $6,   -- field
        $9,   -- fromString
        $11   -- toString
    FROM @RAW.CSV_STAGE/changelog.csv.gz
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.CSV_STAGE')
ON_ERROR = 'CONTINUE';

-- ---------------------------------------------------------------------------
-- TABLE : RAW.ISSUELINKS — 36 colonnes
-- Positions vérifiées : $1=key  $4=type.name  $8=inwardIssue.key  $23=outwardIssue.key
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE RAW.ISSUELINKS (
    key               VARCHAR,
    type_name         VARCHAR,
    inwardissue_key   VARCHAR,
    outwardissue_key  VARCHAR
)
COMMENT = 'Bronze : liens entre tickets JIRA';

COPY INTO RAW.ISSUELINKS (key, type_name, inwardissue_key, outwardissue_key)
FROM (
    SELECT
        $1,   -- key
        $4,   -- type.name
        $8,   -- inwardIssue.key
        $23   -- outwardIssue.key
    FROM @RAW.CSV_STAGE/issuelinks.csv.gz
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.CSV_STAGE')
ON_ERROR = 'CONTINUE';
