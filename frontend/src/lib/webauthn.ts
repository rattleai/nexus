import { api } from "./api-client"

interface RegistrationOptions {
  publicKey: PublicKeyCredentialCreationOptions
}

interface AuthenticationOptions {
  publicKey: PublicKeyCredentialRequestOptions
}

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let str = ""
  for (const b of bytes) str += String.fromCharCode(b)
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "")
}

function base64urlToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/")
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

/**
 * Check if WebAuthn is supported in the current browser.
 */
export function isWebAuthnSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.PublicKeyCredential &&
    typeof window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === "function"
  )
}

/**
 * Check if a platform authenticator (biometric) is available.
 */
export async function isPlatformAuthenticatorAvailable(): Promise<boolean> {
  if (!isWebAuthnSupported()) return false
  return window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()
}

/**
 * Register a new WebAuthn credential (biometric enrollment).
 */
export async function registerCredential(deviceName?: string): Promise<{ credential_id: string }> {
  const optionsResponse = await api
    .post("auth/webauthn/register/begin")
    .json<RegistrationOptions>()

  const options = optionsResponse.publicKey
  // Decode server-sent base64url values to ArrayBuffers
  options.challenge = base64urlToBuffer(options.challenge as unknown as string)
  options.user.id = base64urlToBuffer(options.user.id as unknown as string)
  if (options.excludeCredentials) {
    options.excludeCredentials = options.excludeCredentials.map((cred) => ({
      ...cred,
      id: base64urlToBuffer(cred.id as unknown as string),
    }))
  }

  const credential = (await navigator.credentials.create({
    publicKey: options,
  })) as PublicKeyCredential

  const attestationResponse = credential.response as AuthenticatorAttestationResponse

  const result = await api
    .post("auth/webauthn/register/complete", {
      json: {
        id: credential.id,
        raw_id: bufferToBase64url(credential.rawId),
        response: {
          attestation_object: bufferToBase64url(attestationResponse.attestationObject),
          client_data_json: bufferToBase64url(attestationResponse.clientDataJSON),
        },
        type: credential.type,
        device_name: deviceName ?? "This device",
      },
    })
    .json<{ credential_id: string }>()

  // Store credential ID for auto-suggesting biometric login
  try {
    localStorage.setItem("nxs-webauthn-credential", result.credential_id)
  } catch {
    // ignore
  }

  return result
}

/**
 * Authenticate using a registered WebAuthn credential (biometric login).
 */
export async function authenticateWithCredential(): Promise<{ access_token: string }> {
  const optionsResponse = await api
    .post("auth/webauthn/authenticate/begin")
    .json<AuthenticationOptions>()

  const options = optionsResponse.publicKey
  options.challenge = base64urlToBuffer(options.challenge as unknown as string)
  if (options.allowCredentials) {
    options.allowCredentials = options.allowCredentials.map((cred) => ({
      ...cred,
      id: base64urlToBuffer(cred.id as unknown as string),
    }))
  }

  const assertion = (await navigator.credentials.get({
    publicKey: options,
  })) as PublicKeyCredential

  const assertionResponse = assertion.response as AuthenticatorAssertionResponse

  return api
    .post("auth/webauthn/authenticate/complete", {
      json: {
        id: assertion.id,
        raw_id: bufferToBase64url(assertion.rawId),
        response: {
          authenticator_data: bufferToBase64url(assertionResponse.authenticatorData),
          client_data_json: bufferToBase64url(assertionResponse.clientDataJSON),
          signature: bufferToBase64url(assertionResponse.signature),
          user_handle: assertionResponse.userHandle
            ? bufferToBase64url(assertionResponse.userHandle)
            : null,
        },
        type: assertion.type,
      },
    })
    .json<{ access_token: string }>()
}

/**
 * Check if this device has a saved credential for biometric login.
 */
export function hasSavedCredential(): boolean {
  try {
    return !!localStorage.getItem("nxs-webauthn-credential")
  } catch {
    return false
  }
}
