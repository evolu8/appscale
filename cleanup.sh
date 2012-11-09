# Remove logs, keys and tar balls
rm -f ./AppDB/hadoop-0.20.0/logs/*;
rm -f ./AppDB/hbase/hbase-0.20.0-alpha/logs/*;
rm -f ./AppDB/hypertable/0.9.2.5/log/*;
rm -f ./AppDB/logs/*;
rm -f /var/cassandra/*/*;
rm -f /var/voldemort/*/*;
rm -f ./.appscale/secret.key;
rm -f ./.appscale/ssh.key.private;
rm -f ./AppLoadBalancer/log/*;
rm -f /tmp/*.log;
rm -f ./.appscale/*log;
rm -f ./.appscale/certs/*;
rm -rf ./downloads;


ssh -i ~/.appscale/appscale 192.168.104.209 ~/clear.sh;
ssh -i ~/.appscale/appscale 192.168.104.209 reboot -h now;
ssh -i ~/.appscale/appscale 192.168.104.208 ~/clear.sh;
ssh -i ~/.appscale/appscale 192.168.104.208  reboot -h now;
ssh -i ~/.appscale/appscale 192.168.104.210 ~/clear.sh;
ssh -i ~/.appscale/appscale 192.168.104.210  reboot -h now;
ssh -i ~/.appscale/appscale 192.168.104.200 ~/clear.sh;
ssh -i ~/.appscale/appscale 192.168.104.200  reboot -h now;
ssh -i ~/.appscale/appscale 192.168.104.204 ~/clear.sh;
ssh -i ~/.appscale/appscale 192.168.104.204  reboot -h now;
ssh -i ~/.appscale/appscale 192.168.104.205 ~/clear.sh;
ssh -i ~/.appscale/appscale 192.168.104.205  reboot -h now;
ssh -i ~/.appscale/appscale 192.168.104.206 ~/clear.sh;
ssh -i ~/.appscale/appscale 192.168.104.206  reboot -h now;
ssh -i ~/.appscale/appscale 192.168.104.207 ~/clear.sh;

/etc/ssh/ssh_config

   StrictHostKeyChecking no
   UserKnownHostsFile=/dev/null

https://github.com/shatterednirvana/appscale/commit/7c404301b4fa5586ace0f965e876a9c0569b5dfc

appscale/AppServer/google/appengine/api/taskqueue/taskqueue_rabbitmq.py
https://raw.github.com/nlake44/appscale/71d2cf523d76b4b14f99a3d53dada18499e7741b/AppServer/google/appengine/api/taskqueue/taskqueue_rabbitmq.py


svn checkout http://206.117.3.13/var/repo/HubApplication/Branches/Enterprise

---
:master: 192.168.104.200
:appengine:
- 192.168.104.229
- 192.168.104.228
:database:
- 192.168.104.200
- 192.168.104.222


appscale-run-instances -force -verbose --ips ~/ips.yaml --file ~/Enterprise --table hypertable --appengine 40


Wait before entering email.



07 11 15
12 13 14


cd ~/appscale-tools/appscale-utils/src/
./restore-hypertable.sh appscale translateapi___AccountDomain___
./restore-hypertable.sh appscale translateapi___EnterpriseAccount___
./restore-hypertable.sh appscale translateapi___EnterpriseUser___
./restore-hypertable.sh appscale translateapi___UserTouchPoint___


translateapi



<?xml version='1.0' encoding='utf-8'?>
<HubApplication>
	<limits>
  	  <account type='freemium'>
    	<trial_period>30</trial_period>
    	<max_translations_per_day>500</max_translations_per_day>
    	<max_translations_per_mounth>1000</max_translations_per_mounth>
		<max_translations_per_hour>1000</max_translations_per_hour>
    	<tts_enabled>False</tts_enabled>
    	<chat_enabled>False</chat_enabled>
  	  </account>
	  <account type='premium'>
	    <trial_period>-1</trial_period>
	    <max_translations_per_day>-1</max_translations_per_day>
	    <max_translations_per_mounth>-1</max_translations_per_mounth>
	    <tts_enabled>True</tts_enabled>
	    <chat_enabled>True</chat_enabled>
	  </account>
	  <account type='enterprise'>
	    <trial_period>-1</trial_period>
	    <max_translations_per_day>-1</max_translations_per_day>
	    <max_translations_per_mounth>-1</max_translations_per_mounth>
	    <tts_enabled>True</tts_enabled>
	    <chat_enabled>False</chat_enabled>
	  </account>
	</limits>
	<engines>
      <engine key='detectlanguage'>
      	<engineName>GOOGLE</engineName>
      	<webServiceUrl>http://appscale-image0:18001</webServiceUrl>
      </engine>
      <!-- API credentials used for translation in LW.py -->
      <engine key='LWAccess1'>
        <engineName>LW.py</engineName>
        <webServiceUrl>https://lwaccess.languageweaver.com</webServiceUrl>
        <api_version>/v2</api_version>
		<languages_path>/user/</languages_path>
		<blocking_translate_path>/translation</blocking_translate_path>
		<non_blocking_translate_path>/translation-async</non_blocking_translate_path>
        <apiKey>137d200938a6c82bbd3c6801e57c20c20c2a9a20</apiKey>
        <translationAccountId>10194</translationAccountId>
		<languageAccountId>10193</languageAccountId>
      </engine>
	  <!-- API credentials used for LWpairs -->
	  <engine key='LWPair1'>
        <engineName>LWPair</engineName>
        <webServiceUrl>https://lwaccess.languageweaver.com</webServiceUrl>
		<path>/v1/user/</path>
        <apiKey>43d1e8d5e06965c5143957593e63adab92e2ffc3</apiKey>
        <accountID>10193</accountID>
      </engine>
	  <!--ToD URL-->
	  <engine key='BeGlobalSandBox'>
        <engineName>LWPairForTouchPoint</engineName>
        <webServiceUrl>https://192.168.109.14</webServiceUrl>
		<api_version>/v2</api_version>
		<blocking_translate_path>/translation</blocking_translate_path>
		<non_blocking_translate_path>/translation-async</non_blocking_translate_path>
		<fileTranslationPath>/v2/translation-async/file/</fileTranslationPath>
		<URLTranslationPath>/v2/translation-async/url/</URLTranslationPath>
      </engine>
    </engines>
    <urls>
      <HubGatewayURL>https://secure.freetranslation.com/HubGateway/service.asp</HubGatewayURL> <!--production db-->
	  <!--<HubGatewayURL>https://staging-secure.freetranslation.com/HubGateway/serviceDev.asp</HubGatewayURL>--> <!--staging db-->
	  <!--urls used to access BeGlobal when trying to login with an enterprise user-->
	  <BeGlobalUrl>https://192.168.109.13</BeGlobalUrl>
	  <BeGlobalAccountPath>/translationServerClient/getUserAccountByUsername</BeGlobalAccountPath>
	  <secureWebSiteURL>http://secure.freetranslation.com/freesubscription</secureWebSiteURL>
	  <logFilePath>/var/log/appscale/giraffe/GIRAFFE.log</logFilePath>
    </urls>
	<hubParameters>
		<WTWTranslationCacheTTL>1200</WTWTranslationCacheTTL> <!--How long a WTW translation is kept in the cache--><!-- 20 minutes-->
		<WTWauthorizationCacheTTL>0</WTWauthorizationCacheTTL> <!--How long the credentials of a WTW user are kept in the cache--> <!-- never expire-->
		<normalTranslationCacheTTL>86400</normalTranslationCacheTTL> <!--How long a regular translation (not WTW) is kept in the cache--> <!-- 1 day-->
		<URLTranslationCacheTTL>1200</URLTranslationCacheTTL> <!--How long a URL translation is kept in the cache--> <!-- 20 minutes-->
		<EnumLanguagesCacheTTL>900</EnumLanguagesCacheTTL> <!--How long the language pairs for a user are kept in the cache--> <!-- 15 minutes-->
		<defaultCacheTTL>86400</defaultCacheTTL> <!--Default calue for cacge TTL--> <!-- 1 day-->
		<loginCacheTTL>86400</loginCacheTTL> <!--TTL for cache used for freemium, premium and enterprise user authentication-->
		<configCacheTTL>86400</configCacheTTL> <!--TTL for the cache that is used to keep the hub parameter values -->
		<authorizationTokenTTL>30</authorizationTokenTTL> <!--TTL for the cache used to store the user token generated for the iTunes protocol--> <!-- unit measure is days-->
		<logCachedTranslations>true</logCachedTranslations> <!-- enable logging for reporting for cached translations for WTW-->
		<maximumRorationPeriod>15</maximumRorationPeriod> <!-- time that the cron job wait for logFile rotation --> <!--unit measure is minutes-->
		<serverIP>192.168.122.116</serverIP> <!--The server IP, used only for reporting-->
		<maxBatchLogEntries>500</maxBatchLogEntries>
	</hubParameters>
	<hubDeployment>
		<deploymentPlatform>Appscale</deploymentPlatform> <!-- allowed values are Appscale or GAE -->
		<!--<deploymentPlatform>GAE</deploymentPlatform>-->
	</hubDeployment>		
</HubApplication>

 /enterpriseAccount?operation=set&touchPointId=2841&accountId=10555&apiKey=bbd8a6e9815cc0c33a5a104d9b8d70a8463c9ee1&userId=1574

and this one to add domains to that account: /updateDomain?operation=create&url=http://staging-www.easytranslator.com&accountId=10555

/?callback=fun3&action=wstranslate&srcText=test&srcLang=it&srcLangCode=true&trgLang=en&trgLangCode=true&format=jsonp&engine=LW&domainName=http%3A%2F%2Fstaging-www.easytranslator.com&touchPointId=2841&pathname=/stg3-test.html&mc=true&csc=true

http://192.168.104.200:19996/_ah/admin

test1
2pm 120 threads, 100 throttle, cached translations fail at 1/2million reqs. secondary web node failed.
10:30 120 threads, 5800 req/min throttle. 12:14 still running well at 94r/s 600,000 done no errors 1am 870000 96r/s 8:00am the following day 3,400,000 done started getting 503s service down 
through f5 and appscale ballancer 96req/second throttled. 4:30pm start. FAILED after 2 hr 700,000 done

10:30am Mon 22/10/12 throttld @5600r/m  running with rabbit fix on head and scp flag. Not through f5. actually report 92.6r/s latency started at 303ms and settled at 420ms. 2hrs no failures
12:39pm no throttle 120 client threads through f5. Starts at 140r/s throughput. Av latency 770ms. occasional errors (below 1%) at 12:45pm. Test manually stopped after 19 mins completing 86K reqs. 0.3% error.

$APPSCALE_HOME/AppServer/appcfg.py download_data --filename guestbook_appscale.csv --url=http://192.168.1.9/apps/guestbook/_ah/remote_api --application guestbook --auth_domain appscale



