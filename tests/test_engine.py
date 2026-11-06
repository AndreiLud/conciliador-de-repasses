"""Engine against tiny worlds: every error type must be caught, every trap must stay quiet."""
import pytest

from src.generator.generate import DEFAULT_ERRORS, DEFAULT_TRAPS
from tests.conftest import small_config

ERROR_COUNTS = {"comissao_taxa_errada": 2, "comissao_plano_antigo": 1, "taxa_pagamento_errada": 2,
                "cupom_plataforma_cobrado": 2, "estorno_nao_descontado": 2, "estorno_duplicado": 2,
                "pedido_duplicado": 3, "pedido_ausente": 2, "transferencia_divergente": 2, "repasse_duplicado": 1}


def test_clean_world_has_no_divergence(run_world):
    world, result = run_world(small_config())
    assert [d for d in result.divergences if d.status in ("confirmada", "revisao")] == []


def test_sql_recalculation_matches_reference_implementation(run_world):
    world, result = run_world(small_config())
    diff = result.con.sql("SELECT count(*) FROM order_line_comparison WHERE dif_liquido <> 0").fetchone()[0]
    missing = result.con.sql("SELECT count(*) FROM order_line_comparison WHERE linha_id IS NULL").fetchone()[0]
    assert diff == 0 and missing == 0


@pytest.mark.parametrize("error_type", list(DEFAULT_ERRORS))
def test_planted_error_is_detected_with_the_right_type(run_world, error_type):
    world, result = run_world(small_config(errors={error_type: ERROR_COUNTS[error_type]}))
    planted = world.answer_key
    assert len(planted) == ERROR_COUNTS[error_type]
    confirmed = {d.chave: d for d in result.divergences if d.status == "confirmada"}
    for case in planted.to_dict("records"):
        assert case["chave"] in confirmed, f"{error_type} not detected: {case}"
        d = confirmed[case["chave"]]
        assert d.tipo == error_type
        assert d.valor_centavos == case["valor_centavos"]
    assert len(confirmed) == len(planted), "no extra divergences"


@pytest.mark.parametrize("trap_type", list(DEFAULT_TRAPS))
def test_trap_is_not_flagged(run_world, trap_type):
    counts = {"arredondamento_centavos": 15, "ajuste_manual_legitimo": 5, "estorno_complementar": 2,
              "pix_devolvido_reenviado": 2}
    world, result = run_world(small_config(traps={trap_type: counts[trap_type]}))
    traps = world.traps[world.traps["tipo"] == trap_type]
    assert len(traps) == counts[trap_type]
    flagged = {d.chave for d in result.divergences if d.status in ("confirmada", "revisao")}
    assert flagged.isdisjoint(set(traps["chave"]))
    assert flagged == set()


def test_natural_traps_are_present_and_quiet(run_world):
    world, result = run_world(small_config())
    kinds = set(world.traps["tipo"])
    assert {"pedido_virada_de_semana", "cancelado_antes_do_preparo", "estorno_da_plataforma"} <= kinds
    flagged = {d.chave for d in result.divergences if d.status in ("confirmada", "revisao")}
    assert flagged.isdisjoint(set(world.traps["chave"]))


def test_refund_without_owner_goes_to_the_ambiguous_queue(run_world):
    cfg = small_config(errors={"estorno_nao_descontado": 2}, refund_hidden_owner_share=1.0,
                       refund_not_deducted_hidden=2)
    world, result = run_world(cfg)
    keys = set(world.answer_key["chave"])
    amb = {d.chave for d in result.before_aggregation if d.opcoes}
    assert keys <= amb


# Every error type has a look-alike situation that is legitimate and must stay quiet.
TWINS = {
    "comissao_taxa_errada": "arredondamento_centavos",        # cent differences inside the tolerance
    "comissao_plano_antigo": "pedido_antes_da_troca",          # old plan applied to orders made before the change
    "taxa_pagamento_errada": "credito_tabela_nova",           # credit fee changes on 15/10 for the Essencial plan
    "cupom_plataforma_cobrado": "cupom_do_restaurante",        # coupon funded by the restaurant is deducted
    "estorno_nao_descontado": "estorno_da_plataforma",        # refunds owned by the platform are not deducted
    "estorno_duplicado": "estorno_complementar",              # second legitimate refund with the same value
    "pedido_duplicado": "pedido_virada_de_semana",            # order of Sunday night paid in the next week
    "pedido_ausente": "cancelado_antes_do_preparo",           # cancelled before preparation, not paid
    "transferencia_divergente": "ajuste_manual_legitimo",     # adjustment with ticket changes the total
    "repasse_duplicado": "pix_devolvido_reenviado",           # returned Pix sent again
}


@pytest.mark.parametrize("error_type", list(TWINS))
def test_each_error_type_has_a_quiet_twin(run_world, error_type):
    twin = TWINS[error_type]
    traps = {"arredondamento_centavos": 15, "ajuste_manual_legitimo": 4, "estorno_complementar": 2,
             "pix_devolvido_reenviado": 2}
    world, result = run_world(small_config(traps={twin: traps[twin]} if twin in traps else None))
    flagged = {d.chave for d in result.divergences if d.status in ("confirmada", "revisao")}
    assert flagged == set(), f"{twin} raised {flagged}"
    orders = world.orders.drop_duplicates("pedido_id")
    if twin in world.traps["tipo"].unique():
        assert (world.traps["tipo"] == twin).sum() > 0
    elif twin == "pedido_antes_da_troca":
        rp = world.restaurant_plans
        changed = rp[rp.duplicated("restaurante_id", keep=False)]
        change = changed.dropna(subset=["vigencia_fim"]).set_index("restaurante_id")["vigencia_fim"]
        before = orders[orders["restaurante_id"].isin(change.index)]
        before = before[before["criado_em"].dt.date <= before["restaurante_id"].map(change)]
        assert len(before) > 0
    elif twin == "credito_tabela_nova":
        assert ((orders["forma_pagamento"] == "credito") & (orders["criado_em"].dt.date.astype(str) >= "2026-10-15")).any()
    elif twin == "cupom_do_restaurante":
        assert (orders["cupom_custeio"] == "restaurante").any()
    else:
        raise AssertionError(f"twin {twin} not present in the world")
