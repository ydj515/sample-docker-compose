-- ─────────────────────────────────────────────────────────────
-- Normalize pricing seed for deployment
-- ─────────────────────────────────────────────────────────────

delete from codex_model_price_policy
where model in ('gpt-5-codex', 'gpt-5.2-codex');

-- OpenAI 공식 API pricing 기준 (2026-04-29 확인)
insert into codex_model_price_policy
    (model, input_price_per_1m, cached_input_price_per_1m, output_price_per_1m, reasoning_price_per_1m, currency, version, effective_from, effective_to)
values
    ('gpt-5.4', 2.50, 0.25, 15.00, 0.00, 'USD', 'openai-api-pricing-2026-04-29', '2025-01-01', null)
on conflict (model, version) do update set
    input_price_per_1m = excluded.input_price_per_1m,
    cached_input_price_per_1m = excluded.cached_input_price_per_1m,
    output_price_per_1m = excluded.output_price_per_1m,
    reasoning_price_per_1m = excluded.reasoning_price_per_1m,
    currency = excluded.currency,
    effective_from = excluded.effective_from,
    effective_to = excluded.effective_to;
