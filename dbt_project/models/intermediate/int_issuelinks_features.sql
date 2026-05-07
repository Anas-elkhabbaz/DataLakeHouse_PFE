-- Intermédiaire : features de liens entre tickets par issue

WITH base AS (
    SELECT * FROM {{ ref('stg_issuelinks') }}
)

SELECT
    key,
    COUNT(*)                                                       AS n_links_total,
    COUNT(CASE WHEN UPPER(type_name) = 'DUPLICATE'         THEN 1 END) AS n_duplicates,
    COUNT(CASE WHEN UPPER(type_name) = 'BLOCKS'
               AND inwardissue_key IS NOT NULL             THEN 1 END) AS n_blocks,
    COUNT(CASE WHEN UPPER(type_name) = 'BLOCKS'
               AND outwardissue_key IS NOT NULL            THEN 1 END) AS n_blocked_by,
    COUNT(CASE WHEN UPPER(type_name) = 'RELATES'           THEN 1 END) AS n_relates,
    COUNT(CASE WHEN UPPER(type_name) LIKE '%CLONES%'       THEN 1 END) AS n_clones

FROM base
WHERE key IN (SELECT key FROM {{ ref('int_issues_cleaned') }})
GROUP BY key
