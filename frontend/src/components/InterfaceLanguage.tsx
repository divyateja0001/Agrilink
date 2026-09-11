import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { normalizeInterfaceLanguage, translateInterfaceText } from '@/interfaceTranslations'

const originalText = new WeakMap<Text, string>()
const originalAttributes = new WeakMap<Element, Map<string, string>>()
const translatedAttributes = ['aria-label', 'placeholder', 'title', 'alt'] as const

function translateTextNode(node: Text, language: string) {
  const current = node.data
  let original = originalText.get(node)
  if (!original) {
    const candidate = translateInterfaceText(current, language)
    if (candidate === current) return
    original = current
    originalText.set(node, original)
  } else {
    const expected = translateInterfaceText(original, language)
    if (current !== expected && current !== original) {
      const candidate = translateInterfaceText(current, language)
      if (candidate !== current) {
        original = current
        originalText.set(node, original)
      }
    }
  }
  const translated = translateInterfaceText(original, language)
  if (node.data !== translated) node.data = translated
}

function translateElementAttributes(element: Element, language: string) {
  let originals = originalAttributes.get(element)
  for (const attribute of translatedAttributes) {
    const current = element.getAttribute(attribute)
    if (!current) continue
    let original = originals?.get(attribute)
    if (!original) {
      const candidate = translateInterfaceText(current, language)
      if (candidate === current) continue
      original = current
      if (!originals) {
        originals = new Map()
        originalAttributes.set(element, originals)
      }
      originals.set(attribute, original)
    }
    const translated = translateInterfaceText(original, language)
    if (current !== translated) element.setAttribute(attribute, translated)
  }
}

function translateTree(root: Node, language: string) {
  if (root.nodeType === Node.TEXT_NODE) {
    translateTextNode(root as Text, language)
    return
  }
  if (root.nodeType !== Node.ELEMENT_NODE) return
  const element = root as Element
  translateElementAttributes(element, language)
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    if (node.nodeType === Node.TEXT_NODE) translateTextNode(node as Text, language)
    else translateElementAttributes(node as Element, language)
    node = walker.nextNode()
  }
}

export function InterfaceLanguage() {
  const { i18n } = useTranslation()
  const language = normalizeInterfaceLanguage(i18n.resolvedLanguage ?? i18n.language)

  useEffect(() => {
    document.documentElement.lang = language
    document.documentElement.dir = 'ltr'
    translateTree(document.body, language)

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'characterData') translateTextNode(mutation.target as Text, language)
        if (mutation.type === 'childList') mutation.addedNodes.forEach((node) => translateTree(node, language))
        if (mutation.type === 'attributes') translateElementAttributes(mutation.target as Element, language)
      }
    })
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...translatedAttributes],
    })
    return () => observer.disconnect()
  }, [language])

  return null
}
