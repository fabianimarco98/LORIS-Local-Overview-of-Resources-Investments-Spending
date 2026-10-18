import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import loris_service as svc
from banking import net_worth as nw

FIX = Path(__file__).resolve().parent / "fixtures" / "mock_statements"


def make_store():
    store = nw.NetWorthStore()
    nw.add_holding(store, "conto", "Conto A", "LIQUID_CASH")
    nw.add_holding(store, "broker", "Broker B", "INVESTMENTS")
    nw.add_holding(store, "cash", "Contanti", "OTHER")
    return store


class TestNetWorthStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "net_worth.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_gives_empty_store(self):
        store = nw.load(self.path)
        self.assertEqual(store.holdings, [])
        self.assertEqual(store.snapshots, [])

    def test_round_trip(self):
        store = make_store()
        nw.add_snapshot(store, "2026-01-15", {"conto": 1000, "broker": 5000.5}, note="Q1")
        nw.save(store, self.path)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], nw.SCHEMA_VERSION)
        loaded = nw.load(self.path)
        self.assertEqual([h.id for h in loaded.holdings], ["conto", "broker", "cash"])
        self.assertEqual(loaded.snapshots[0].values, {"conto": 1000.0, "broker": 5000.5})
        self.assertEqual(loaded.snapshots[0].note, "Q1")

    def test_save_is_atomic_and_leaves_no_temp_files(self):
        nw.save(make_store(), self.path)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ["net_worth.json"])

    def test_failed_save_keeps_previous_file(self):
        store = make_store()
        nw.add_snapshot(store, "2026-01-15", {"conto": 1000})
        nw.save(store, self.path)
        before = self.path.read_text(encoding="utf-8")
        store.snapshots[0].values["conto"] = object()   # non serializzabile
        with self.assertRaises(TypeError):
            nw.save(store, self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ["net_worth.json"])

    def test_corrupt_file_raises_instead_of_resetting(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            nw.load(self.path)

    def test_env_var_overrides_default_path(self):
        old = os.environ.get("LORIS_NET_WORTH")
        os.environ["LORIS_NET_WORTH"] = str(self.path)
        try:
            self.assertEqual(nw.default_path(), self.path)
        finally:
            if old is None:
                del os.environ["LORIS_NET_WORTH"]
            else:
                os.environ["LORIS_NET_WORTH"] = old


class TestValidation(unittest.TestCase):
    def test_duplicate_and_unknown_class_rejected(self):
        store = make_store()
        with self.assertRaises(ValueError):
            nw.add_holding(store, "conto", "Altro")
        with self.assertRaises(ValueError):
            nw.add_holding(store, "x", "X", "NOT_A_CLASS")

    def test_snapshot_rejects_bad_input(self):
        store = make_store()
        for bad in ({"conto": float("nan")}, {"conto": "abc"}, {"ghost": 1}, {}):
            with self.assertRaises(ValueError):
                nw.add_snapshot(store, "2026-01-15", bad)
        with self.assertRaises(ValueError):
            nw.add_snapshot(store, "15/01/2026", {"conto": 1})
        self.assertEqual(store.snapshots, [])

    def test_archived_holding_not_accepted_in_new_snapshot_but_history_kept(self):
        store = make_store()
        nw.add_snapshot(store, "2026-01-15", {"conto": 100, "cash": 50})
        nw.archive_holding(store, "cash")
        with self.assertRaises(ValueError):
            nw.add_snapshot(store, "2026-04-15", {"conto": 120, "cash": 10})
        nw.add_snapshot(store, "2026-04-15", {"conto": 120})
        totals = nw.totals_by_class(store)
        self.assertEqual(totals.loc["2026-01-15", "total"], 150.0)   # lo storico non si riscrive
        self.assertEqual(totals.loc["2026-04-15", "total"], 120.0)

    def test_unique_holding_id(self):
        store = make_store()
        self.assertEqual(nw.unique_holding_id(store, "Conto Principale!"), "conto_principale")
        self.assertEqual(nw.unique_holding_id(store, "Conto A"), "conto_a")
        nw.add_holding(store, "conto_a", "Conto A", "LIQUID_CASH")
        self.assertEqual(nw.unique_holding_id(store, "Conto A"), "conto_a_2")
        self.assertEqual(nw.unique_holding_id(store, "€€€"), "voce")

    def test_same_date_replaces_snapshot(self):
        store = make_store()
        nw.add_snapshot(store, "2026-01-15", {"conto": 100})
        nw.add_snapshot(store, "2026-01-15", {"conto": 200})
        self.assertEqual(len(store.snapshots), 1)
        self.assertEqual(store.snapshots[0].values["conto"], 200.0)


class TestAnalysis(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        nw.add_snapshot(self.store, "2026-04-15", {"conto": 1100, "broker": 5500})   # inserito per primo ma più recente
        nw.add_snapshot(self.store, "2026-01-15", {"conto": 1000, "broker": 5000})

    def test_snapshots_are_sorted_by_date(self):
        self.assertEqual([s.date for s in self.store.snapshots], ["2026-01-15", "2026-04-15"])

    def test_deltas_between_consecutive_snapshots(self):
        d = nw.deltas(self.store)
        self.assertTrue(d.loc[0, "delta"] != d.loc[0, "delta"])      # NaN sul primo
        self.assertEqual(d.loc[1, "total"], 6600.0)
        self.assertEqual(d.loc[1, "delta"], 600.0)
        self.assertAlmostEqual(d.loc[1, "delta_pct"], 10.0)

    def test_totals_by_class(self):
        t = nw.totals_by_class(self.store)
        self.assertEqual(t.loc["2026-04-15", "LIQUID_CASH"], 1100.0)
        self.assertEqual(t.loc["2026-04-15", "INVESTMENTS"], 5500.0)

    def test_empty_store_analysis_is_safe(self):
        empty = nw.NetWorthStore()
        self.assertTrue(nw.deltas(empty).empty)
        self.assertTrue(nw.totals_by_class(empty).empty)
        self.assertTrue(nw.history_df(empty).empty)

    def test_update_due(self):
        self.assertTrue(nw.is_update_due(nw.NetWorthStore()))
        self.assertEqual(nw.days_since_last(self.store, "2026-05-15"), 30)
        self.assertFalse(nw.is_update_due(self.store, today="2026-06-30"))   # 76 giorni
        self.assertTrue(nw.is_update_due(self.store, today="2026-07-30"))    # 106 giorni


class TestPrefill(unittest.TestCase):
    def test_prefill_from_statement_balances(self):
        data = svc.load_portfolio(FIX, apply_overrides=False)
        acc = data.summary.accounts_summary
        real = acc[~acc["is_tracker"]].iloc[0]
        store = nw.NetWorthStore()
        nw.add_holding(store, "linked", "Collegato", "LIQUID_CASH", linked_account_id=real["account_id"])
        nw.add_holding(store, "manual", "Manuale", "OTHER")
        nw.add_holding(store, "gone", "Archiviato", "OTHER", linked_account_id=real["account_id"])
        nw.archive_holding(store, "gone")
        pre = nw.prefill_from_portfolio(store, data.summary)
        self.assertEqual(set(pre), {"linked"})
        self.assertAlmostEqual(pre["linked"], round(float(real["balance"]), 2))

    def test_prefill_without_accounts_is_empty(self):
        class Dummy:
            accounts_summary = None
        self.assertEqual(nw.prefill_from_portfolio(make_store(), Dummy()), {})


class TempStoreMixin:
    """Punta LORIS_NET_WORTH a un file temporaneo: i test non toccano mai input/ reale."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "net_worth.json"
        self._old = os.environ.get("LORIS_NET_WORTH")
        os.environ["LORIS_NET_WORTH"] = str(self.path)
        store = make_store()
        nw.save(store, self.path)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("LORIS_NET_WORTH", None)
        else:
            os.environ["LORIS_NET_WORTH"] = self._old
        self.tmp.cleanup()


class TestService(TempStoreMixin, unittest.TestCase):
    def test_record_and_history(self):
        svc.record_snapshot("2026-01-15", {"conto": 1000, "broker": 5000})
        svc.record_snapshot("2026-04-15", {"conto": 1100, "broker": 5500}, note="Q2")
        hist = svc.get_net_worth_history()
        self.assertEqual(len(hist["snapshots"]), 2)
        self.assertIsNone(hist["deltas"][0]["delta"])
        self.assertEqual(hist["deltas"][1]["delta"], 600.0)
        self.assertEqual(hist["snapshots"][1]["note"], "Q2")
        json.dumps(hist)   # serializzabile (API/agente)

    def test_empty_history_requires_update(self):
        hist = svc.get_net_worth_history()
        self.assertTrue(hist["update_due"])
        self.assertIsNone(hist["days_since_last"])
        self.assertEqual(hist["deltas"], [])

    def test_invalid_snapshot_does_not_modify_file(self):
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            svc.record_snapshot("2026-01-15", {"ghost": 1})
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


class TestAgentTool(TempStoreMixin, unittest.TestCase):
    def test_tool_is_registered_read_only_and_scrubs_names(self):
        from agents import PortfolioContext, build_portfolio_registry
        data = svc.load_portfolio(FIX, apply_overrides=False)
        reg = build_portfolio_registry(PortfolioContext(data.summary, data.df_tx, data.stats, 2.5))
        self.assertIn("net_worth_history", reg.names())
        self.assertEqual(reg.execute("net_worth_history", {}).data["snapshots"], 0)
        store = nw.load(self.path)
        nw.archive_holding(store, "cash")
        nw.add_holding(store, "iban", "Conto IT60X0542811101000000123456", "LIQUID_CASH")
        nw.save(store, self.path)
        svc.record_snapshot("2026-01-15", {"conto": 1000, "iban": 50})
        res = reg.execute("net_worth_history", {})
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.data["latest_date"], "2026-01-15")
        self.assertNotIn("IT60X0542811101000000123456", json.dumps(res.data))


try:
    from fastapi.testclient import TestClient
    import app as api_app
    HAVE_API = True
except Exception:   # httpx/fastapi non installati: i test API vengono saltati
    HAVE_API = False


@unittest.skipUnless(HAVE_API, "fastapi TestClient non disponibile")
class TestApi(TempStoreMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(api_app.app)

    def test_snapshot_then_history(self):
        r = self.client.post("/api/net-worth/snapshot", json={"date": "2026-01-15", "values": {"conto": 10}})
        self.assertEqual(r.status_code, 200, r.text)
        h = self.client.get("/api/net-worth/history").json()
        self.assertEqual(h["snapshots"][0]["values"], {"conto": 10.0})

    def test_bad_snapshot_is_422(self):
        r = self.client.post("/api/net-worth/snapshot", json={"date": "oggi", "values": {"conto": 10}})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/net-worth/snapshot", json={"date": "2026-01-15", "values": {"ghost": 10}})
        self.assertEqual(r.status_code, 422)

    def test_corrupt_file_is_reported_not_reset(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.client.get("/api/net-worth/history").status_code, 500)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
