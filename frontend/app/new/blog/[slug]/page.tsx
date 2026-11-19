import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BlogArticle } from "@/components/site/BlogViews";
import { POSTS, findPost, postPath } from "@/components/site/blog-posts";

// Only published slugs exist; anything else is a 404.
export const dynamicParams = false;

export function generateStaticParams() {
  return POSTS.map((p) => ({ slug: p.slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const post = findPost(params.slug);
  if (!post) return {};
  return {
    title: { absolute: `${post.seoTitle ?? post.title} | Anril AI` },
    description: post.description,
    alternates: { canonical: postPath(post.slug) },
    // Setting openGraph here replaces the site-wide one, so the share image is repeated (without it,
    // Facebook and WhatsApp previews of an article show no picture).
    openGraph: {
      type: "article",
      siteName: "Anril AI",
      locale: "en_IN",
      url: `https://www.anrilaitech.com${postPath(post.slug)}`,
      title: post.seoTitle ?? post.title,
      description: post.description,
      publishedTime: post.published,
      modifiedTime: post.updated,
      authors: [post.author],
      images: [{ url: "/og-image-v2.png", width: 1200, height: 630, alt: post.title }],
    },
  };
}

export default function BlogPostPage({ params }: { params: { slug: string } }) {
  const post = findPost(params.slug);
  if (!post) notFound();
  return <BlogArticle post={post} />;
}
