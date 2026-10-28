# control-plane

Infra do control plane da Easy Goal (ADR 061 no `easy-labs`): os serviços que vão rodar na VPS
(Coolify, Infisical, observabilidade). Hoje roda na máquina de dev que simula a VPS (`10home`).
Só infra; nenhum segredo versionado (`.env` de cada serviço é gerado e fica fora do git).

## Serviços

| Serviço | Pasta | Acesso | Estado |
|---|---|---|---|
| Infisical (segredos) | `infisical/` | `http://localhost:8080` (só 127.0.0.1) | etapa 2 |

## Infisical

```bash
scripts/bootstrap-env.sh infisical        # uma vez: gera infisical/.env (600), não imprime valores
cd infisical && docker compose up -d --wait
curl -s localhost:8080/api/status         # "message":"Ok"
```

- **Backup obrigatório:** `infisical/.env` (principalmente `ENCRYPTION_KEY`) num gerenciador de senhas,
  fora desta máquina. Sem ele os segredos guardados são irrecuperáveis. Backup do volume `pg_data`
  também (é onde os segredos cifrados ficam).
- Primeiro acesso: criar o admin em `http://localhost:8080` (cadastro é só por convite depois disso).
- CLI (`~/.local/bin/infisical`, versão fixada e checksum conferido):
  `infisical login --domain http://localhost:8080` → `infisical init` no repo do projeto →
  `infisical run --env=dev -- <comando>` injeta as variáveis no processo, sem `.env` em disco.
- Versões fixadas (imagem `v0.167.2`): atualizar de propósito, nunca `latest`, sempre com backup antes.
