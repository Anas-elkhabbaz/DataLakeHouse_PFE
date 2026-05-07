-- Macro de nettoyage de texte JIRA (6 étapes enchaînées).
-- Utilisé dans int_issues_cleaned et int_comments_aggregated.
-- Paramètre : col_expr — expression SQL contenant le texte brut (ex: summary, comment_body)
{% macro clean_jira_text(col_expr) %}
    TRIM(
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(
                            REGEXP_REPLACE(
                                COALESCE({{ col_expr }}, ''),
                                '<[^>]+>', ' '              -- 1. Balises HTML
                            ),
                            '\\{code[^}]*\\}.*?\\{code\\}', ' ', 1, 0, 'si'  -- 2. Blocs {code}
                        ),
                        '\\{noformat[^}]*\\}.*?\\{noformat\\}', ' ', 1, 0, 'si'  -- 3. {noformat}
                    ),
                    '\\[~[^\\]]+\\]', ' '   -- 4. Mentions utilisateur [~user]
                ),
                'https?://\\S+', ' '        -- 5. URLs
            ),
            '[\\n\\r\\t ]{2,}', ' '         -- 6. Espaces/sauts de ligne multiples
        )
    )
{% endmacro %}
