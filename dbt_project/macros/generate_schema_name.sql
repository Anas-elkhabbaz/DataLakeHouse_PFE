-- Override du comportement dbt par défaut.
-- Sans ce macro, dbt concatène le schéma cible et le schéma custom
-- (ex: public_staging). Avec ce macro, on utilise le nom exact défini
-- dans dbt_project.yml (+schema: staging → schéma = STAGING).
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
