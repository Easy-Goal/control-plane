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
- Token do dispositivo: cookie `HttpOnly`, `Secure`, `SameSite=Strict`, com só o hash no servidor.
- Senha com scrypt. TOTP de 6 dígitos, cada código vale uma vez. Cinco erros bloqueiam aquele dispositivo por 15 minutos, sem afetar os outros. `cplane account reset` libera.
- Sessão só em memória, por dispositivo: 1 h sem uso ou 12 h no total. Tela aberta sem ninguém mexendo não conta como uso. Reiniciar o painel pede login de novo.
- Pedido de outra origem é recusado, assim como nome de host desconhecido.
- Com o Tailscale identificando a origem, o token fica preso àquela máquina da tailnet. Em outra, é recusado e gera alerta.
- `--acoes` fora do laboratório só liga com acesso remoto, porque depende destas regras.

## O que este controle não garante

- Dispositivo aprovado e roubado, com sessão aberta, parece legítimo até ser revogado. Produção pede o autenticador de novo para reduzir isso.
- A lista protege o painel. Cofre, Coolify, OpenObserve e SSH têm acessos próprios: mantenha as ACLs da tailnet.
- Quem tem root na principal pode alterar o registro e ler o segredo do autenticador em `state/auth.json`.
- Sem Tailscale identificando a origem, valem só o token e o login.
- A sessão de leitura do cofre dura 1 h: `cplane --remoto --cofre` precisa ser reaberto no terminal.

## Eventos

**Máquinas** mostra os eventos de `state/security.jsonl`, e o Quadro destaca o que pede atenção: dispositivo revogado tentando entrar, token em outra máquina, bloqueio e código de recuperação usado. Pedidos aguardando também aparecem no Quadro.
