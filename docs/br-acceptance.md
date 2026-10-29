# Acceptance of the core requirements (BR1–BR8)

Each core business requirement is accepted on real data in two ways: the Spark Gold tables that serve it equal the independent DuckDB golden reference row for row (`results/validation-gold.json`, 23 of 23 tables equal), and a property test pins its defining rule (`tests/test_golden_kpis.py`). Each is also shown in both frontends. The screenshots below were taken on 2026-10-29: the Streamlit app on the validated snapshot (Spark Gold, commit `774e951`, validated 2026-10-03) and the public site at transitometer.vercel.app. Injected faults never appear in this table; they belong to the labelled robustness runs.

| Requirement | Gold tables equal to golden | Property test | Streamlit page | Site page | Screenshots |
|---|---|---|---|---|---|
| BR1 on-time performance | `otp_summary`, `otp_route_hour`, `delay_sanity_summary` | `test_stale_and_terminal_edges`, `test_stale_events_reported_by_position` | On-time performance | `/reliability/on-time` | [app](evidence/br/br1-app.jpg), [site](evidence/br/br1-web.jpg) |
| BR2 headways and bunching | `headways` (2,956,930 rows), `headway_regularity`, `headway_summary` | `test_headway_ratio_edges_and_same_vehicle` | Headways and bunching | `/reliability/headways` | [app](evidence/br/br2-app.jpg), [site](evidence/br/br2-web.jpg) |
| BR3 missing trips | `trip_delivery`, `missing_trip_summary`, `missing_by_route`, `terminal_events`, `terminal_summary` | `test_missing_trip_classes`, `test_terminal_arrivals_from_vehicle_positions` | Trip delivery | `/reliability/missing-trips` | [app](evidence/br/br3-app.jpg), [site](evidence/br/br3-web.jpg) |
| BR4 travel time and delay attribution | `segments`, `segment_travel_stats`, `trip_delay_attribution`, `delay_attribution_summary` | `test_segments_and_delay_attribution`, `test_segments_never_cross_a_vehicle_change` | Where delay builds up | `/diagnostics/delay` | [app](evidence/br/br4-app.jpg), [site](evidence/br/br4-web.jpg) |
| BR5 route scorecards with confidence intervals | `route_scorecard`, `route_hour_scorecard` | `test_route_bootstrap_ci_recomputed_independently`, `test_route_hour_scorecard_needs_enough_trips` | Route scorecards | `/diagnostics/route-scorecards` | [app](evidence/br/br5-app.jpg), [site](evidence/br/br5-web.jpg) |
| BR6 early warning | `warning_decisions`, `early_warning_summary` | `test_early_warning_decisions` | Early warning | `/diagnostics/early-warning` | [app](evidence/br/br6-app.jpg), [site](evidence/br/br6-web.jpg) |
| BR7 feed health | `feed_quality_metrics`, `feed_quality_score`, `position_jumps` | `test_feed_quality_checks`, `test_outage_threshold_is_strict` | Feed health | `/data/feed-health` | [app](evidence/br/br7-app.jpg), [site](evidence/br/br7-web.jpg) |
| BR8 stop reliability (rider view) | `stop_hour_reliability` (392,788 rows) | `test_stop_hour_reliability_matches_on_time_events` (parity with BR1) | Stop reliability | `/diagnostics/stops` | [app](evidence/br/br8-app.jpg), [site](evidence/br/br8-web.jpg) |

BR6 also has a held-out target: on the held-out day (2026-09-23, bus) both rules pass precision ≥ 60 %, "ends late" at 83 % (recall 75 %) and "gets bunched" at 80 % (recall 54 %), each with a higher F1 than its naive baseline (`early_warning_summary`; shown on the Early warning page).

To retake the screenshots: run the app on the snapshot (`TRANSITOMETER_APP_SOURCE=snapshot streamlit run src/transitometer/app/main.py`) and open each page above; the site pages are public.
