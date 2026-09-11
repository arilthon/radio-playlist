"""Resumo de estado com distinção entre observações atuais e persistidas."""
import time


def summarize(active, activities, indicators):
    now = time.time()
    capture = dict(activities.get('capture', {'status':'unknown'}))
    worker = dict(activities.get('worker', {'status':'unknown'}))
    alerts = []
    codes={401:'Login serviço musical expirado ou revogado. Autorize novamente no terminal.',403:'serviço musical negou acesso. Confira permissões da conta e do aplicativo.',404:'Faixa ou playlist não encontrada. Confira o cadastro e as escolhas manuais.'}
    if worker.get('http_status') in codes:
        worker['message']=codes[worker['http_status']]
    if not active:
        if worker.get('status') == 'error':
            alerts.append(worker.get('message','O monitor encerrou com erro. Execute o diagnóstico.'))
        capture['status'] = 'stopped'
        worker['status'] = 'stopped'
        if indicators['queue_real'] + indicators['queue_dry']:
            alerts.append('Rádio parada com músicas na fila. Inicie no modo correspondente para processar.')
    else:
        if capture['status'] == 'listening' and now-capture.get('updated',0)>45:
            capture['status']='stale'
            alerts.append('Sem confirmação recente de leitura da rádio. Confira a conexão; isso não significa necessariamente uma faixa perdida.')
        if capture['status'] == 'reconnecting':
            alerts.append(capture.get('message','Rádio desconectada; tentando reconectar.'))
        if capture['status'] == 'unknown':
            alerts.append('Aguardando telemetria. Se o processo é antigo, reinicie a rádio.')
        if worker['status'] == 'rate_limited':
            alerts.append('Limite serviço musical atingido. A captura continua e as músicas ficam na fila.')
        if worker['status'] in ('error','retrying'):
            alerts.append(worker.get('message','Falha no acesso ao serviço musical; a faixa permanece pendente.'))
        mode = activities.get('session',{}).get('mode')
        if mode == 'dry' and indicators['queue_real']:
            alerts.append('Há inclusões reais pendentes, mas esta rádio está em simulação.')
        if mode == 'real' and indicators['queue_dry']:
            alerts.append('Há simulações pendentes; elas só serão processadas no modo de simulação.')
        if mode == 'radio' and indicators['queue_real']+indicators['queue_dry']:
            alerts.append('O modo de captura não processa a fila do serviço musical.')
    for part in (capture,worker):
        part['retry_seconds'] = max(0,round(part.get('retry_at',0)-now)) if active else 0
    return dict(capture=capture,worker=worker,alerts=alerts)
