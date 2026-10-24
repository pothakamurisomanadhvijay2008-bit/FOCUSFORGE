'use strict';

const loginForm = document.querySelector('#loginForm');
const registerForm = document.querySelector('#registerForm');
const message = document.querySelector('#authMessage');

function showMode(mode) {
  const registering = mode === 'register';
  loginForm.classList.toggle('hidden', registering);
  registerForm.classList.toggle('hidden', !registering);
  document.querySelector('#authTitle').textContent = registering ? 'Create your account' : 'Welcome back';
  document.querySelector('#authIntro').textContent = registering
    ? 'Set up an account to keep your sessions private to you.'
    : 'Sign in to continue to your dashboard.';
  message.textContent = '';
}

async function submitCredentials(form, endpoint) {
  message.textContent = '';
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        email: form.querySelector('input[type="email"]').value,
        password: form.querySelector('input[type="password"]').value,
      }),
    });
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to sign in. Please try again.');
    window.location.assign('/');
  } catch (error) {
    message.textContent = error.message || 'The server could not be reached. Try again.';
  } finally {
    submit.disabled = false;
  }
}

loginForm.addEventListener('submit', event => {
  event.preventDefault();
  submitCredentials(loginForm, '/api/auth/login');
});
registerForm.addEventListener('submit', event => {
  event.preventDefault();
  submitCredentials(registerForm, '/api/auth/register');
});
document.querySelector('#showRegister').addEventListener('click', () => showMode('register'));
document.querySelector('#showLogin').addEventListener('click', () => showMode('login'));
