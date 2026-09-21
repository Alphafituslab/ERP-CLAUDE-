-- Fase 190 — pedido do usuário: pedidos de venda CANCELADOS e NÃO
-- faturados poderem ser excluídos de vez ("nem aparecer"). Soft-delete
-- (coluna, não DELETE de verdade): pedidos_venda é referenciado por
-- muitas outras tabelas (itens, reservas de estoque, fluxo, comissão
-- etc.) — apagar a linha de verdade arrastaria uma limpeza arriscada em
-- cascata sem necessidade nenhuma, já que o objetivo é só "sumir da
-- lista", não recuperar espaço. Reversível por natureza (nada é perdido).
ALTER TABLE pedidos_venda ADD COLUMN excluido_em TEXT;
ALTER TABLE pedidos_venda ADD COLUMN excluido_por INTEGER REFERENCES usuarios(id);
