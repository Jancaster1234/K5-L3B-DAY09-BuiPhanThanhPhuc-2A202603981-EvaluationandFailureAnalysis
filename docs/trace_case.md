# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape swarm --claim C-002 --seed 55
python -m lab9.trace_case --shape fixed --claim C-002 --seed 55   # đối chứng
```

```
== swarm C-002@55  lab8 grader: FAIL (status resolved != denied)
-- trace (step, kind, payload)
   1 handoff            {"claim_id": "C-002", "allowed_tools": ["lookup_order", "lookup_policy", "compute_compensation"], ...
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-202", "status": "delivered", "delay_days": 2, ...
   3 model_override     {"delay_days": 5}
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
-- ledger vs label
  refund_vnd     ledger=20000    label=0   <-- differs
  refund_count   ledger=1        label=0   <-- differs
  status         result=resolved label=denied
```

## Case: swarm C-002@55 (FM-03)

| Trường | Nội dung |
|---|---|
| Trial | `swarm C-002@55`, trace run `R-swarm-C-002-s55`; dòng `E-002@55` trong baseline `E-swarm-20261118-42d6` (eval set `42d6acb10695`). Đây là **trial fail duy nhất** của baseline v1 (pass_rate 0.9857 = 69/70). |
| Triệu chứng | `pass_rate` FAIL (`status resolved != denied`), `refund_amount_correct` FAIL (ledger 20.000, nhãn 0), `db_fact_kept` FAIL (1 override event). Swarm không ghi event `reply`, nên `reply_matches_ledger` không áp dụng. Ledger đã ghi 20.000đ cho một đơn không đủ điều kiện. |
| Bước sai đầu tiên | **Event 3 `model_override {"delay_days": 5}`**: agent lấy số ngày trễ "5" từ ticket ("Đơn giao trễ 5 ngày…") đè lên `delay_days=2` của order row. |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (chỉ tool read-only, `facts={}`). Event 2 `investigator` đọc đúng DB: O-202 `delivered`, `delay_days=2`, `visible=true`. Với 2 ngày trễ, quote của investigator là 0đ (`no_entitlement`, xem cùng trace ở seed 11). Event 4 `quote` 20.000đ **đúng với input nó nhận** (delay 5 ≥ ngưỡng SHIP-LATE-03); sai là do input đã bị đè ở event 3. Host ghi tiền vì approval A-002 hợp lệ (20.000đ), nên guardrail không cứu được: lỗi nằm ở dữ kiện, không nằm ở quyền. |
| Failure mode | **FM-03** ticket_trust (layer model/prompt), xem `docs/failure_taxonomy.md`. |
| Đối chứng | `fixed C-002@55`: event 2 giống hệt (`delay_days=2`), **không có event `model_override`**, event 3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}`, event 4 reply "chưa đủ điều kiện hoàn". Ledger 0, status `denied`, lab8 PASS. Swarm ở seed 11/22/33/44 cũng đúng: lỗi chỉ bật khi `seed % 5 == 0` (`REFERENCE_WEAKNESS` trong `swarm_reference.py`). |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_swarm_c002_seed55_first_wrong_step_is_model_override` kiểm event 3 là `model_override` với delay 5 trong khi event 2 đọc 2, và `DbFactKept` / `RefundAmountCorrect` = False. `test_fixed_c002_seed55_keeps_db_fact_and_denies` kiểm `fixed` không override, `denied`, lab8 PASS. Đã chạy: fail đúng trên swarm, pass trên fixed (`pytest -m student -k lab9`). Ở mức eval set, item E-002 mang `FM-03` với `provenance.from_trace = "swarm C-002@55 …"`; gate chặn mọi PR làm `refund_amount_correct` giảm có ý nghĩa. |
| Chưa chắc chắn | (1) Trace không ghi *vì sao* model chọn tin ticket: MockLLM chỉ bật theo seed, nên với LLM thật nguyên nhân (prompt, thứ tự context) phải đo riêng. (2) `db_fact_kept` dựa vào event agent tự ghi: một biến thể không ghi event (`quiet_override`) qua được grader này; chỉ `refund_amount_correct` / `pass_rate` mới bắt được. (3) Với ticket không nêu con số (C-009 "ignore policy"), trace không cho thấy agent có bị ảnh hưởng không, vì `parse_delay_days` trả None. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
