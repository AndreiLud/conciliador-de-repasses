"""Name pools for fictitious restaurants. Any match with a real business is a coincidence."""
from __future__ import annotations

CITIES = [
    ("São Paulo", "SP", 0.28), ("Rio de Janeiro", "RJ", 0.15), ("Belo Horizonte", "MG", 0.08),
    ("Curitiba", "PR", 0.07), ("Porto Alegre", "RS", 0.06), ("Salvador", "BA", 0.06),
    ("Recife", "PE", 0.06), ("Fortaleza", "CE", 0.05), ("Brasília", "DF", 0.06),
    ("Campinas", "SP", 0.05), ("Goiânia", "GO", 0.04), ("Florianópolis", "SC", 0.04),
]

# category -> (weight, mean ticket in cents, late night share, name patterns, name pool)
CATEGORIES = {
    "Lanches": (0.16, 4200, 0.09, ["{x} Burger", "Lanchonete {x}", "{x} Lanches", "Hamburgueria {x}"],
                ["do Zé", "Brasa", "Esquina", "Big Bom", "Smash Hall", "Rei do Pão", "Avenida", "Bairro",
                 "Trem Bão", "Garagem", "Monstro", "Chapa Quente", "Prensado", "Cheddar"]),
    "Pizza": (0.12, 7200, 0.10, ["Pizzaria {x}", "{x} Pizzas", "Forno {x}"],
              ["Bella Napoli", "Dom Vito", "Vesúvio", "Nonna Rosa", "Massa Fina", "Calabresa",
               "Forno a Lenha", "Ponto Certo", "Margherita", "San Gennaro", "Toscana", "Borda Dourada"]),
    "Japonesa": (0.08, 9500, 0.03, ["{x} Sushi", "Temakeria {x}", "Restaurante {x}"],
                 ["Sakura", "Kaizen", "Hanami", "Nagoya", "Koi", "Umi", "Tsuki", "Kenzo", "Hikari", "Mizu"]),
    "Brasileira": (0.14, 4600, 0.02, ["Cantina {x}", "Restaurante {x}", "Cozinha {x}", "Tempero {x}"],
                   ["Nossa Senhora Aparecida", "Sabor da Vila", "Mineiro", "da Vó Cida", "Sabor Caseiro",
                    "Paulista", "Fogão de Lenha", "Panela de Barro", "Dona Lurdes", "São Jorge",
                    "Feijão Preto", "Santo Antônio"]),
    "Marmita": (0.10, 2800, 0.01, ["Marmitaria {x}", "{x} Marmitas", "Quentinha {x}"],
                ["da Praça", "Fit", "Boa Mesa", "Caseira", "do Trabalhador", "Bem Servida", "Sustança"]),
    "Açaí": (0.07, 3000, 0.04, ["Açaí {x}", "{x} Açaí"],
             ["Tropical", "da Ilha", "Pará", "Roxo", "Grão", "Point", "Energia"]),
    "Doces": (0.05, 3800, 0.02, ["Doceria {x}", "Confeitaria {x}"],
              ["Brigadeiro", "Doce Lar", "Açúcar Mascavo", "Vó Nina", "Cacau", "Bem Casado"]),
    "Saudável": (0.06, 4300, 0.01, ["{x} Natural", "Verde {x}", "Bowl {x}"],
                 ["Folha", "Raiz", "Equilíbrio", "Quinoa", "Leve", "Horta"]),
    "Árabe": (0.05, 5200, 0.03, ["Esfiharia {x}", "{x} Árabe", "Casa {x}"],
              ["Beirute", "Damasco", "Líbano", "Aladim", "Kebab", "Zaatar"]),
    "Italiana": (0.06, 6800, 0.02, ["Cantina {x}", "Trattoria {x}", "Osteria {x}"],
                 ["Nonno Beppe", "Mamma Mia", "Della Nonna", "Bella Itália", "Tre Fratelli", "Al Dente"]),
    "Padaria": (0.05, 3200, 0.02, ["Padaria {x}", "Panificadora {x}"],
                ["Pão Quente", "Santa Rita", "Trigo de Ouro", "Nova Era", "Real", "Bom Dia"]),
    "Churrasco": (0.06, 6200, 0.03, ["Churrascaria {x}", "Espetinho {x}", "Parrilla {x}"],
                  ["Gaúcha", "Brasa do Sul", "Costela", "Picanha", "Brasa Viva", "Tchê"]),
}

# Similar names appear in pairs, as in real registries (franchises, second units).
NAME_VARIANT_SUFFIXES = [" II", " Express", " Centro", " Unidade 2"]

OWNER_SURNAMES = ["Alves", "Ferreira", "Souza", "Oliveira", "Lima", "Costa", "Ribeiro", "Martins",
                  "Carvalho", "Rocha", "Almeida", "Nascimento", "Araújo", "Barbosa", "Cardoso",
                  "Teixeira", "Moreira", "Mendes", "Nunes", "Freitas", "Pires", "Duarte"]
COMPANY_WORDS = ["Alimentos", "Comércio de Alimentos", "Restaurante", "Gastronomia", "Refeições",
                 "Food Service", "Lanches e Refeições"]
COMPANY_SUFFIXES = ["Ltda", "Ltda ME", "EIRELI", "Ltda EPP", "SLU"]

BANK_ABBREVIATIONS = {
    "NOSSA SENHORA": "N SRA", "SENHORA": "SRA", "RESTAURANTE": "REST", "PIZZARIA": "PIZZ",
    "LANCHONETE": "LANCH", "COMERCIO DE ALIMENTOS": "COM ALIM", "ALIMENTOS": "ALIM",
    "HAMBURGUERIA": "HAMB", "CHURRASCARIA": "CHURR", "CONFEITARIA": "CONF", "PANIFICADORA": "PANIF",
    "MARMITARIA": "MARMIT", "TEMAKERIA": "TEMAK", "GASTRONOMIA": "GASTR", "REFEICOES": "REFEIC",
    "SANTO": "STO", "SANTA": "STA", "SAO": "S", " DA ": " ", " DO ": " ", " DE ": " ",
}

ADJUSTMENT_REASONS = [
    ("Ressarcimento de embalagens danificadas no transporte", 1),
    ("Bônus da campanha de aniversário do bairro", 1),
    ("Devolução de taxa cobrada em duplicidade na semana anterior", 1),
    ("Desconto de material promocional entregue ao restaurante", -1),
    ("Crédito por indisponibilidade do aplicativo no dia 14", 1),
    ("Ajuste de cupom de campanha conjunta aprovado pelo comercial", 1),
    ("Cobrança de maquininha avariada conforme contrato", -1),
    ("Reembolso de entrega refeita por erro do parceiro de entrega", 1),
]

# Support notes typed by the service team, with the informal spelling seen in
# real tickets. The first two pools have a clear owner; the last one does not,
# and its hidden truth is a coin flip.
REFUND_NOTES_RESTAURANT = [
    "cliente informou que faltou o refrigerante", "veio faltando um item do combo",
    "lanche errado, pediu sem cebola e veio com cebola", "pizza veio de outro sabor",
    "cliente disse que o frango veio cru por dentro", "embalagem do restaurante veio aberta",
    "cliente achou cabelo na comida", "porção bem menor que a anunciada no cardápio",
    "loja mandou o pedido de outra pessoa", "faltou a sobremesa do pedido",
    "cliente falou q n veio a coca", "veio frango no lugar de carne",
    "hamburguer trocado, veio o simples e nao o duplo", "batata murcha e queimada segundo a cliente",
    "mandaram so 1 temaki, cliente pediu 2", "pedido incompleto",
    "veio sem o molho que a cliente pagou a parte", "esqueceram o guaraná",
    "açaí sem os complementos pagos", "cliente recebeu marmita de outra pessoa, sacola lacrada",
    "comida azeda, cliente mandou foto", "pastel veio vazio praticamente",
]
REFUND_NOTES_PLATFORM = [
    "entregador não encontrou o endereço", "pedido chegou com 1h de atraso, motoboy parado",
    "parceiro de entrega derrubou o pedido no caminho", "app cobrou o cliente duas vezes",
    "entrega cancelada pelo parceiro depois da retirada", "cliente não recebeu, entregador marcou como entregue",
    "erro no cupom do app, cliente pagou a mais", "rota do entregador errada, pedido rodou a cidade",
    "motoca quebrou no meio do caminho", "rapaz da entrega sumiu com o pedido",
    "cliente esperou 90 min, nenhum entregador disponivel", "cobrança em duplicidade no cartão pelo sistema",
    "pedido deixado no prédio errado", "lacre da sacola rompido durante a entrega",
    "falha no pagamento, cliente cobrado sem pedido confirmado",
    "pedido pronto ficou 50 min na loja esperando coleta", "corrida não saiu e cliente desistiu",
]
REFUND_NOTES_AMBIGUOUS = [
    "cliente insatisfeito com o pedido", "pedido chegou frio", "reclamação aberta pelo cliente, reembolso parcial",
    "cliente pediu reembolso pelo chat", "pedido chegou revirado na sacola", "reembolso por cortesia",
    "pedido com problema",
]

COUPONS_PLATFORM = [("BEMVINDO15", "fixed", 1500), ("TALHER10", "pct", 1000), ("SEXTOU8", "fixed", 800),
                    ("VOLTA12", "fixed", 1200)]
COUPONS_RESTAURANT = [("LOJA10", "pct", 1000), ("COMBO5", "fixed", 500), ("FIEL7", "fixed", 700)]
