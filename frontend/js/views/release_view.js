export const releaseViewTemplate = `
<section class="panel">
  <h2>解笼拨付</h2>
  <p class="hint">仅核验通过的笼可拨付。默认把可用额全额拨给受益人，也可部分解笼。账户余额与冻结同步扣减。</p>
  <p class="hint cutoff-hint">
    索锁截断（焊死乙路径）：未持笼锁的解笼请求一律 409 拒收——无半成品拨付、笼面零增、账户零扣减；
    后到一方只在争用痕留名。双人同解同一笼时，仅持锁成功方落一笔。
  </p>
  <div class="grid-2">
    <div>
      <div class="form-row">
        <div>
          <label>通过态笼</label>
          <select v-model.number="releaseForm.cage_id">
            <option :value="0">请选择</option>
            <option v-for="c in passCages" :key="c.id" :value="c.id">
              {{ c.cage_code }} · 可用 {{ fmt(c.available) }}
            </option>
          </select>
        </div>
        <div>
          <label>金额（空=全额）</label>
          <input type="number" v-model.number="releaseForm.amount" min="0" step="1000" placeholder="全额"/>
        </div>
        <div>
          <label>收款方（空=受益人）</label>
          <input v-model="releaseForm.payee"/>
        </div>
      </div>
      <div class="actions">
        <button class="ok" @click="doRelease">解笼拨付</button>
        <span class="hint" v-if="currentCageLock">
          当前笼锁：{{ currentCageLock.lock_key }} · 持有者 {{ currentCageLock.holder }}
        </span>
        <span class="hint" v-else>当前所选笼无持锁记录，可正常索锁拨付</span>
      </div>
      <div v-if="actionErr && actionErr.indexOf('笼锁') >= 0" class="action-err cutoff-err">
        索锁截断：{{ actionErr }}（未持锁，拨付已正式拒收，笼面零改）
      </div>
    </div>
    <div>
      <table>
        <thead>
          <tr><th>凭证</th><th>笼</th><th>金额</th><th>收款方</th><th>笼代</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in releases" :key="r.id">
            <td>{{ r.release_ref }}</td>
            <td>{{ r.cage_code }}</td>
            <td>{{ fmt(r.amount) }}</td>
            <td>{{ r.payee }}</td>
            <td>{{ r.cage_generation }}</td>
            <td>{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <h3 style="margin-top:14px">本笼争用痕（后到只记争用，零拨付）</h3>
      <table>
        <thead>
          <tr><th>时间</th><th>人</th><th>动作</th><th>详情</th></tr>
        </thead>
        <tbody>
          <tr v-for="x in currentCageContention" :key="x.id">
            <td>{{ x.created_at }}</td>
            <td>{{ x.actor }}</td>
            <td><span class="badge fail">{{ x.action }}</span></td>
            <td>{{ x.detail }}</td>
          </tr>
          <tr v-if="!currentCageContention.length">
            <td colspan="4" class="hint">无争用记录</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
`;
