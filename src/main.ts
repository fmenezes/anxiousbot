function log(msg: string) {
  let app = document.querySelector('#app');
  if (app == null) {
    return;
  }
  app.innerHTML += `<p class="read-the-docs">${msg}</p>
`
}
log(`hi`)
log(`me again`)
