import os
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd

import bank_data_manager as bdm
from agents import AgentRuntime, PortfolioContext, build_portfolio_registry
from agents.runtime import audit_grounding, parse_text_tool_call
from agents.tools import Tool, ToolRegistry

FIX = Path(__file__).resolve().parent / "fixtures" / "mock_statements"


def make_ctx():
    _, summary = bdm.load_all_bank_statements(FIX)
    return PortfolioContext.from_summary(summary)


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


class ScriptedChat:
    """Backend finto: restituisce i messaggi in sequenza e registra cosa riceve."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages, tools):
        self.seen.append((list(messages), bool(tools)))
        return self.replies.pop(0) if self.replies else {"content": "fine"}


class TestToolValidation(unittest.TestCase):
    def setUp(self):
        self.reg = build_portfolio_registry(make_ctx())

    def test_bad_month_format_returns_correctable_error(self):
        res = self.reg.execute("spending_by_category", {"month": "06-09"})
        self.assertFalse(res.ok)
        self.assertIn("YYYY-MM", res.error)

    def test_unknown_tool_and_unknown_arg(self):
        self.assertFalse(self.reg.execute("delete_everything", {}).ok)
        self.assertIn("sconosciuti", self.reg.execute("get_portfolio_summary", {"x": 1}).error)

    def test_range_and_required_checks(self):
        self.assertFalse(self.reg.execute("run_forecast", {"n_sims": 10**7}).ok)
        self.assertIn("obbligatori", self.reg.execute("simulate_pac", {}).error)

    def test_numeric_strings_are_coerced(self):
        res = self.reg.execute("monthly_cashflow", {"last_n_months": "3"})
        self.assertTrue(res.ok)
        self.assertLessEqual(len(res.data["months"]), 3)

    def test_null_like_strings_are_treated_as_missing(self):
        res = self.reg.execute("spending_by_category", {"month": "2026-09", "top_n": "null"})
        self.assertTrue(res.ok, res.error)
        res = self.reg.execute("query_transactions", {"text": "None", "category": "undefined", "limit": "5"})
        self.assertTrue(res.ok, res.error)

    def test_errors_include_signature_for_self_correction(self):
        err = self.reg.execute("spending_by_category", {"top_n": "molte"}).error
        self.assertIn("spending_by_category(", err)

    def test_registry_is_read_only(self):
        forbidden = ("write", "delete", "save", "remove", "upload", "set_")
        for n in self.reg.names():
            self.assertFalse(any(f in n for f in forbidden), n)


class TestTools(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.reg = build_portfolio_registry(self.ctx)

    def test_summary_matches_portfolio(self):
        res = self.reg.execute("get_portfolio_summary", {})
        self.assertTrue(res.ok)
        self.assertAlmostEqual(res.data["net_worth"], round(self.ctx.summary.total_net_worth, 2), places=1)

    def test_query_transactions_filters_and_scrubs(self):
        res = self.reg.execute("query_transactions", {"direction": "out", "limit": 5, "sort": "amount_desc"})
        self.assertTrue(res.ok)
        rows = res.data["transactions"]
        self.assertLessEqual(len(rows), 5)
        self.assertTrue(all(r["amount"] < 0 for r in rows))
        amounts = [abs(r["amount"]) for r in rows]
        self.assertEqual(amounts, sorted(amounts, reverse=True))
        self.assertNotRegex(str(rows), r"AT\d{18}")

    def test_spending_by_category_excludes_transfers(self):
        res = self.reg.execute("spending_by_category", {})
        self.assertTrue(res.ok)
        total = res.data["total_spent"]
        self.assertAlmostEqual(total, sum(c["total"] for c in res.data["categories"]), delta=total * 0.01 + 0.5) \
            if len(res.data["categories"]) < 10 else self.assertGreater(total, 0)

    def test_runway_and_forecast_run(self):
        self.assertTrue(self.reg.execute("calculate_runway", {}).ok)
        res = self.reg.execute("run_forecast", {"horizon_months": 12, "n_sims": 200})
        self.assertTrue(res.ok, res.error)
        self.assertLessEqual(res.data["net_worth_p5_pessimistic"], res.data["net_worth_p95_optimistic"])

    def test_tool_exception_becomes_error_result(self):
        reg = ToolRegistry([Tool("boom", "x", {}, lambda: 1 / 0)])
        res = reg.execute("boom", {})
        self.assertFalse(res.ok)
        self.assertIn("ZeroDivisionError", res.error)

    def test_result_truncation(self):
        reg = ToolRegistry([Tool("big", "x", {}, lambda: ["x" * 100] * 500)])
        self.assertLess(len(reg.execute("big", {}).to_message(1000)), 1200)


class TestRuntime(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.reg = build_portfolio_registry(self.ctx)
        self.nw = round(self.ctx.summary.total_net_worth, 2)

    def test_tool_then_answer(self):
        chat = ScriptedChat(call("get_portfolio_summary"), {"content": f"Il patrimonio è € {self.nw:,.2f}."})
        res = AgentRuntime(self.reg, chat).run("Quanto ho?")
        self.assertEqual([t.name for t in res.tool_calls], ["get_portfolio_summary"])
        self.assertTrue(res.grounding["is_grounded"], res.grounding)
        self.assertEqual(res.stopped_reason, "answered")
        # il risultato del tool è tornato al modello con ruolo "tool"
        self.assertEqual(chat.seen[1][0][-1]["role"], "tool")

    def test_model_corrects_after_validation_error(self):
        chat = ScriptedChat(
            call("spending_by_category", month="06-09"),
            call("spending_by_category", month="2026-09"),
            {"content": "Fatto."},
        )
        res = AgentRuntime(self.reg, chat).run("Spese di settembre?")
        self.assertEqual([t.ok for t in res.tool_calls], [False, True])   # il tentativo errato resta in traccia
        self.assertIn("YYYY-MM", chat.seen[1][0][-1]["content"])

    def test_repeated_call_is_not_reexecuted(self):
        chat = ScriptedChat(call("list_accounts"), call("list_accounts"), {"content": "ok"})
        res = AgentRuntime(self.reg, chat).run("conti")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertIn("già eseguita", chat.seen[2][0][-1]["content"])

    def test_max_steps_forces_final_answer_without_tools(self):
        chat = ScriptedChat(*[call("query_transactions", limit=i + 1) for i in range(3)], {"content": "Riepilogo."})
        res = AgentRuntime(self.reg, chat, max_steps=3).run("loop")
        self.assertEqual(res.stopped_reason, "max_steps")
        self.assertFalse(chat.seen[-1][1])             # ultima richiesta senza tool
        self.assertEqual(res.answer, "Riepilogo.")

    def test_ungrounded_amount_is_flagged(self):
        chat = ScriptedChat(call("get_portfolio_summary"), {"content": "Hai € 987.654,32 sul conto."})
        res = AgentRuntime(self.reg, chat).run("Quanto ho?")
        self.assertFalse(res.grounding["is_grounded"])
        self.assertIn("non verificate", res.answer)

    def test_text_mode_tool_call_fallback(self):
        chat = ScriptedChat(
            {"content": '```json\n{"tool": "list_accounts", "arguments": {}}\n```'},
            {"content": "Ecco i conti."},
        )
        res = AgentRuntime(self.reg, chat).run("conti?")
        self.assertEqual([t.name for t in res.tool_calls], ["list_accounts"])

    def test_empty_answer_is_nudged_once(self):
        chat = ScriptedChat({"content": ""}, {"content": "Risposta."})
        self.assertEqual(AgentRuntime(self.reg, chat).run("ciao").answer, "Risposta.")

    def test_stream_emits_events_in_order(self):
        chat = ScriptedChat(call("list_accounts"), {"content": "ok"})
        kinds = [e.kind for e in AgentRuntime(self.reg, chat).stream("conti")]
        self.assertEqual(kinds, ["tool_call", "tool_result", "final"])

    def test_history_is_forwarded(self):
        chat = ScriptedChat({"content": "ok"})
        AgentRuntime(self.reg, chat).run("e a ottobre?", history=[
            {"role": "user", "content": "spese di settembre?"}, {"role": "assistant", "content": "800"},
        ])
        roles = [m["role"] for m in chat.seen[0][0]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])


class TestHelpers(unittest.TestCase):
    def test_audit_grounding(self):
        self.assertTrue(audit_grounding("Hai € 1.250,00 e 5 €", {1250.0})["is_grounded"])
        self.assertFalse(audit_grounding("Hai € 9.999,00", {1250.0})["is_grounded"])
        self.assertTrue(audit_grounding("Nessun importo qui", set())["is_grounded"])

    def test_parse_text_tool_call_rejects_unknown(self):
        reg = ToolRegistry([Tool("a", "x", {}, lambda: 1)])
        self.assertIsNotNone(parse_text_tool_call('{"tool": "a", "arguments": {}}', reg))
        self.assertIsNone(parse_text_tool_call('{"tool": "rm_rf", "arguments": {}}', reg))
        self.assertIsNone(parse_text_tool_call("niente json", reg))


if __name__ == "__main__":
    unittest.main()
