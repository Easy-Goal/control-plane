# Máquinas e acesso remoto

Quem é a máquina e quem é a pessoa. Nome, IP e navegador só ajudam a reconhecer um pedido: nunca autorizam nada.

## Dois conceitos

- **Instalação:** onde o control plane roda. Papel: principal (uma por conta, normalmente a VPS), lab ou teste.
- **Dispositivo:** o que acessa a principal, com dono, classe e estado.

| Classe | Pode | Quem aplica |
|---|---|---|
| Operação | Consultar e agir. Produção, criar ou preparar cliente, aprovar e revogar pedem o autenticador de novo | Servidor |
| Consulta | Só ler | Servidor |
| Lab/teste | Ver e agir só em dev e staging. Produção nem chega ao navegador: na implantação, os outros passos mostram só o estado, sem nomes | Servidor |

## Abrir para outras máquinas

Na principal, em um terminal:

```sh
cplane machine promote            # recusa se a conta já tiver outra principal
cplane account create             # usuário, senha e autenticador. Só existe no terminal
cplane --remoto --sem-navegador
tailscale serve --bg --https=443 http://127.0.0.1:4700
```

O painel continua escutando só em `127.0.0.1`. Quem publica é o `tailscale serve`, e só na tailnet. Se o nome na tailnet não for detectado, informe com `--host cp.sua-rede.ts.net`.

Guarde os códigos de recuperação no seu gerenciador de senhas, fora da máquina. Eles são mostrados uma vez.

Depois de promover, publique o `workspace.toml`, para as outras máquinas saberem qual é a principal. A promoção confere o repositório antes, mas duas máquinas promovidas ao mesmo tempo, sem publicar, não se enxergam.

## Aprovar um dispositivo

1. O dispositivo abre o endereço e pede acesso. Nada fica visível, e um código aparece na tela dele.
2. Quem aprova confere o pedido e digita o código, em **Máquinas** ou no terminal da principal:

   ```sh
   cplane devices approve <código> --classe operacao
   ```

3. O dispositivo entra com usuário, senha e código do autenticador.

O primeiro dispositivo é sempre aprovado pelo terminal. O terminal da principal também é a recuperação se todos forem perdidos.

| Comando, na principal | O que faz |
|---|---|
| `cplane devices` | Lista dispositivos e pedidos |
| `cplane devices class <id> <classe>` | Troca a classe |
| `cplane devices revoke <id>` | Corta o acesso na hora |
| `cplane account status` | Mostra a conta e os códigos de recuperação restantes |
| `cplane account reset` | Troca senha e autenticador e derruba as sessões |

## Registrar outra instalação

Em uma máquina de lab ou teste, para a principal saber que ela existe:

```sh
cplane connect https://cp.sua-rede.ts.net
cplane connect --status
```

O registro só identifica a instalação. Ele não dá acesso a dados nem traz valores do cofre.

## Regras

- Dispositivo novo só consegue pedir acesso. Login só é aceito de dispositivo aprovado.
- Token do dispositivo: cookie `HttpOnly`, `Secure`, `SameSite=Strict`, sem `Domain`, com só o hash no servidor. Pela tailnet, os nomes são `__Host-cp_device` e `__Host-cp_session`: outra máquina de `*.ts.net` não consegue plantar um cookie com esse nome. O nome sem prefixo (`cp_device`, `cp_session`) só vale no acesso local, e pela tailnet é ignorado.
- Senha com scrypt. TOTP de 6 dígitos, cada código vale uma vez. Cinco erros bloqueiam aquele dispositivo por 15 minutos, sem afetar os outros. `cplane account reset` libera.
- Sessão só em memória, por dispositivo: 1 h sem uso ou 12 h no total. Tela aberta sem ninguém mexendo não conta como uso. Reiniciar o painel pede login de novo.
- Pedido de outra origem é recusado, assim como nome de host desconhecido.
- Com `--remoto`, todo pedido precisa ter origem conhecida, inclusive os de `/api/auth/`. Vale a máquina que o `tailscale whois` identifica pelo último item do `X-Forwarded-For` que o `tailscale serve` coloca. Sem esse cabeçalho, com endereço fora da tailnet ou com o `whois` falhando, o pedido é recusado com 403 e gera o alerta `origin_refused` (só o motivo e o IP, um por motivo a cada 10 minutos). Falha do `whois` não fica em cache: o próximo pedido pergunta de novo.
- Exceção explícita: o acesso local, nesta mesma máquina, em `http://127.0.0.1:4700` ou `http://localhost:4700`, sem `X-Forwarded-For` (por exemplo, por túnel SSH). Ele segue como antes: dispositivo aprovado e login.
- O token fica preso à origem em que o dispositivo pediu acesso: aprovado por uma máquina da tailnet, só vale nela; pedido no acesso local, só vale no acesso local. Fora disso, é recusado e gera alerta `node_mismatch`.
- `--acoes` fora do laboratório só liga com acesso remoto, porque depende destas regras.

## O que este controle não garante

- Dispositivo aprovado e roubado, com sessão aberta, parece legítimo até ser revogado. Produção pede o autenticador de novo para reduzir isso.
- A lista protege o painel. Cofre, Coolify, OpenObserve e SSH têm acessos próprios: mantenha as ACLs da tailnet.
- Quem tem root na principal pode alterar o registro e ler o segredo do autenticador em `state/auth.json`.
- No acesso local, valem só o token e o login. Um processo na própria principal que alcance `127.0.0.1:4700` (contêiner com `network_mode: host`, por exemplo) pode pedir acesso ou forjar o `X-Forwarded-For` com o IP de outra máquina da tailnet. Não use `network_mode: host` na principal.
- Pelo navegador, em `http://localhost`, o Safari descarta cookie `Secure`: no acesso local, use Chrome, Edge ou Firefox.
- A sessão de leitura do cofre dura 1 h: `cplane --remoto --cofre` precisa ser reaberto no terminal.

## Teste manual pendente com o Tailscale real

Os testes automáticos simulam o `tailscale serve`. Antes de expor a principal, confirme na VPS que ele **sobrescreve ou
acrescenta** o `X-Forwarded-For` que vem do cliente. Se ele repassar o cabeçalho do cliente sem mexer, o cliente escolhe
o IP, e a amarração à máquina deixa de valer.

1. Na principal: `cplane --remoto --sem-navegador` e `tailscale serve --bg --https=443 http://127.0.0.1:4700`.
2. De outra máquina da tailnet, sem cookie, mande um IP falso:

   ```sh
   curl -s -X POST -H 'Content-Type: application/json' -H 'X-Forwarded-For: 100.64.0.1' \
     -d '{"name":"teste-xff"}' https://cp.<rede>.ts.net/api/auth/request
   ```

3. Em **Máquinas** (ou em `state/security.jsonl`), o evento `unknown_device` de `teste-xff` precisa mostrar em `address`
   o IP real da máquina que mandou o pedido (`tailscale ip -4` nela), e não `100.64.0.1`. Depois, recuse o pedido.
4. Com o mesmo `curl`, confira o `Set-Cookie`: o nome começa com `__Host-cp_device`.
5. Na principal, `curl -s http://127.0.0.1:4700/api/auth/state -H 'Host: cp.<rede>.ts.net'` (sem `X-Forwarded-For`)
   responde 403 e gera `origin_refused`.

Se o passo 3 mostrar `100.64.0.1`, não exponha o painel: abra uma tarefa para trocar a origem pelo cabeçalho que o
`serve` assina (`Tailscale-User-Login`) ou por outra prova.

## Eventos

**Máquinas** mostra os eventos de `state/security.jsonl`, e o Quadro destaca o que pede atenção: dispositivo revogado tentando entrar, token em outra máquina, bloqueio e código de recuperação usado. Pedidos aguardando também aparecem no Quadro.
