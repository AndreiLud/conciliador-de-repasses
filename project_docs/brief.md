# Brief

## O problema

Um marketplace de delivery repassa toda semana o dinheiro das vendas para os restaurantes. Do valor dos pedidos saem comissão, taxa de pagamento, cupons pagos pelo restaurante e estornos. O financeiro precisa conferir se o valor repassado bate com o que deveria ser, achar as divergências, descobrir a causa e explicar ao restaurante. Hoje isso é feito em planilha, linha a linha.

## A ferramenta

Recebe os arquivos que o financeiro já recebe, recalcula o repasse esperado de cada pedido com o contrato vigente, cruza com o extrato de repasse e com o extrato bancário, encontra cada divergência, classifica a causa, escreve a carta para o restaurante e gera o relatório da semana.

## Princípios

1. **A IA não faz conta.** Todo valor em dinheiro é calculado em código, em centavos inteiros. Taxas são pontos-base inteiros.
2. **Regra primeiro.** O modelo de linguagem só entra onde a regra não resolve bem: evidência em texto livre ou mais de uma causa possível para o mesmo valor.
3. **Saída verificável.** Toda resposta do modelo é JSON validado por schema. Todo número escrito pelo modelo precisa existir nos dados. Toda evidência citada precisa existir no caso.
4. **Incerteza vira revisão.** Confiança baixa, regra e IA discordando ou resposta reprovada nas checagens: o caso vai para a fila de revisão humana.
5. **Tudo local.** O modelo roda na máquina (Ollama ou servidor do llama.cpp). Nenhum dado sai, nenhuma chave de API.

## Escopo

* Marketplace fictício: Talher. Taxas e planos ilustrativos.
* 200 restaurantes em 12 cidades, um mês de pedidos (cinco semanas fechadas, de 28/09/2026 a 01/11/2026).
* Erros plantados com gabarito e armadilhas para medir falso positivo.
* Duas formas de uso: site estático no GitHub Pages (vitrine, sem API) e app local em Streamlit.

## Fora do escopo

* Integração com sistemas reais (banco de dados, API bancária).
* Envio das cartas. A ferramenta gera o texto; quem envia é uma pessoa.
* Disputas e renegociação de contrato.
