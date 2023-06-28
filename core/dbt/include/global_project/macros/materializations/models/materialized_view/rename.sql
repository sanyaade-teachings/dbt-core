{% macro rename_materialized_view_sql(materialized_view, name, from_intermediate=False) %}
    {{- log('Applying RENAME to: ' ~ materialized_view.fully_qualified_path) -}}
    {{- adapter.dispatch('rename_materialized_view_sql', 'dbt')(materialized_view, name, from_intermediate) -}}
{% endmacro %}


{% macro default__rename_materialized_view_sql(materialized_view, name, from_intermediate=False) %}
    {{ exceptions.raise_compiler_error("Materialized views have not been implemented for this adapter.") }}
{% endmacro %}